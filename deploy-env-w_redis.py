import glob
import json
import os
from botocore.exceptions import ClientError
import boto3
import toml
from utilities import Utilities
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(funcName)s %(levelname)s %(message)s')
logging.getLogger('boto').setLevel(logging.CRITICAL)

script_dir = os.path.abspath(os.path.dirname(__file__))
base_path = os.path.abspath(os.path.join(script_dir, os.pardir))

aws_profile, aws_region, environment, stackname_base, first_stack = Utilities().parse_args()

utils = Utilities()


def sendParametersToConfig(toml_file, current_tags, projnm, st, e, e_tag):
    stack_name = environment + '-' + projnm + "-" + st
    toml_data = toml.load(toml_file)
    toml_data[e]['deploy']['parameters']['stack_name'] = stack_name

    current_tags[e_tag] = 'Environment=' + e
    toml_data[e]['deploy']['parameters']['tags'] = current_tags

    toml_string = toml.dumps(toml_data)
    with open(toml_file, 'w') as c:
        c.write(toml_string)
    c.close()
    return stack_name


def resetCustomStackValues(t, e):
    logging.info('Resetting values in ' + t + ' for environment ' + e)
    toml_data = toml.load(t)
    stack_name = ""
    tagging = []
    toml_data[e]['deploy']['parameters']['stack_name'] = stack_name
    toml_data[e]['deploy']['parameters']['tags'] = tagging
    toml_string = toml.dumps(toml_data)
    with open(t, 'w') as c:
        c.write(toml_string)
    c.close()


def updateRedisAuthKey(session, env, cf):
    secrets_stack_name = env + '-' + stackname_base + '-secrets'
    redis_secret_export = 'RedisSecManArn'
    redis_sec_man_arn = utils.search_exports(session, redis_secret_export, secrets_stack_name)
    if redis_sec_man_arn is None:
        logging.critical('Unable to retrieve Redis Auth Key from Secret Stack '+secrets_stack_name)
        exit(2)
    else:
        secret_response = session.client('secretsmanager').get_secret_value(
            SecretId=redis_sec_man_arn,
        )
        authkey = json.loads(secret_response['SecretString'])['AUTH']
        data = toml.load(cf)

        parameter_overrides = data[env]['deploy']['parameters']['parameter_overrides']
        try:
            parameter_index = int(parameter_overrides.index('AuthToken='))
            parameter_overrides[parameter_index] = 'AuthToken=' + authkey
            data[env]['deploy']['parameters']['parameter_overrides'] = parameter_overrides
            toml_string = toml.dumps(data)
            with open(cf, 'w') as config_toml:
                config_toml.write(toml_string)
            config_toml.close()
        except ValueError:
            pass

    return redis_sec_man_arn, authkey


def updateRedisSecret(session, env, redis_sec_man_arn, authkey):
    redis_stack_name = env + '-' + stackname_base + '-redis'
    redis_host_export = 'RedisHost'
    redis_host = utils.search_exports(session, redis_host_export, redis_stack_name)
    if redis_host is None:
        logging.critical('Unable to retrieve Redis HOST from Redis Stack '+redis_stack_name)
        exit(2)
    else:
        new_secret_string = {'hostname': redis_host, 'AUTH': authkey}
        session.client('secretsmanager').update_secret(
            SecretId=redis_sec_man_arn,
            SecretString=json.dumps(new_secret_string)
        )
    pass


def sendStorageArtifacts(session,bp):
    S3 = session.client('s3')
    s3_bucket = environment + '-' + stackname_base + '-storage-artifacts-'+aws_region
    artifacts_dir = bp + '/artifacts'
    for file in os.scandir(path=artifacts_dir):
        try:
            full_file_path = artifacts_dir+'/'+str(file.name)
            key = 'init/'+str(file.name)
            S3.upload_file(full_file_path,s3_bucket,key)
            logging.info('Sent artifact '+str(file.name) + ' to '+s3_bucket)
        except ClientError as e:
            logging.error(e)
            return False
    return True


def doDeployStacks(session):

    current_mandatory_tags = []
    stack_status_values = ['CREATE_COMPLETE', 'UPDATE_COMPLETE']
    with open(base_path + '/config/current_tags', 'r') as tags:
        for line in tags.readlines():
            current_mandatory_tags.append(line.rstrip('\n'))
    tags.close()
    glob_pattern = base_path + '/[0-9]*'
    dirs = glob.glob(glob_pattern, recursive=False)
    sorted_dirs = sorted(dirs)
    for stacks_dir in sorted_dirs:
        files = []
        for file in os.scandir(path=stacks_dir):
            if file.name.endswith('yaml'):
                files.append(file.name)
        sorted_files = sorted(files)
        for filename in sorted_files:
            if int(filename.split('-', 1)[0]) < int(first_stack):
                pass
            else:
                basename = filename.split('.', 1)[0]
                stack_type = basename.split('-', 1)[1]
                config_file = stacks_dir + '/config/' + basename + '.toml'
                template_file = stacks_dir + '/' + basename + '.yaml'
                resetCustomStackValues(config_file, environment)
                tag_names = [str(item.split('=', 1)[0]).lower() for item in current_mandatory_tags]
                e_tag = tag_names.index('environment')
                stack_name = sendParametersToConfig(config_file, current_mandatory_tags, stackname_base, stack_type,
                                                    environment, e_tag)
                if basename.split('-', 1)[1] == "redis":
                    redis_sec_man_arn, authkey = updateRedisAuthKey(session, environment, config_file)
                logging.info('Deploying stack ' + basename.split('-', 1)[1] + ' with configuration from ' + config_file)
                if basename.split('-', 1)[1] == "functions":
                    command = 'sam build --template ' + template_file
                    os.system(command)
                command = 'sam deploy  --profile ' + aws_profile + '  --region ' + aws_region + ' --config-env ' + \
                          environment + ' --config-file ' + config_file + ' --template ' \
                          + template_file
                logging.info(command)
                os.system(command)
                cloudform_client = session.client('cloudformation')
                get_stack = cloudform_client.describe_stacks(StackName=stack_name)
                stack_status = get_stack['Stacks'][0]['StackStatus']
                if any(x in stack_status for x in stack_status_values) is False:
                    logging.critical(
                        'Unable to proceed with the deployment, the state of ' + stack_name + ' is ' + stack_status)
                    exit(2)
                if basename.split('-', 1)[1] == "storage":
                    sendStorageArtifacts(session,base_path)
                if basename.split('-', 1)[1] == "redis":
                    updateRedisSecret(session, environment, redis_sec_man_arn, authkey)


def main():
    session = boto3.Session(profile_name=aws_profile, region_name='us-east-1')
    ec2_regions = session.client('ec2').describe_regions()
    available_regions = []
    for region in ec2_regions['Regions']:
        available_regions.append(region['RegionName'])
    if aws_region not in available_regions:
        logging.critical('invalid region: '+aws_region)
        exit(2)

    doDeployStacks(session)


if __name__ == "__main__":
    main()
