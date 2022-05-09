import argparse
import sys


# This class contains a very basic and generic argument collection method which will work for most stack deployments

class Utilities:
    def __init__(self):
        self.export_value = None
        self.cf_exports = None
        self.cloudform_client = None
        self.exporting_stack_id = None
        self.stackname_base = None
        self.environment = None
        self.aws_region = None
        self.first_stack = None
        self.aws_profile = None
        self.illegal_characters = ['!', '@', '#', '&', '(', ')', '[', '{', '}', ']', ':', ';', '\'', ',', '?', '/',
                                   '\\', '*', '~',
                                   '$', '^', '+', '=', '<', '>']

        self.valid_env = ['dev', 'qa', 'uat', 'prod']

        self.parser = argparse.ArgumentParser()
        self.parser.add_argument("--awsprofile", type=str, help="the AWS profile name for this session")
        self.parser.add_argument("--awsregion", type=str, help="AWS region in which resources will be deployed")
        self.parser.add_argument("--env", type=str, help="Deployment Environment", choices=['prod', 'uat', 'qa', 'dev'])
        self.parser.add_argument("--stacknamebase", type=str,
                                 help="the URL context used to call the API ex. ersgateway")
        self.parser.add_argument("--firststack", type=str, help="number prefix of the first stack to run in order")

        if len(sys.argv) == 0:
            print("Arguments required")
            self.parser.print_help()
            exit(1)
        else:
            self.args = self.parser.parse_args()

    def parse_args(self):
        if self.args.firststack is None:
            self.first_stack = 0
        else:
            self.first_stack = str(self.args.firststack)

        if self.args.awsprofile is None:
            print('An AWS Profile name must be specified')
            self.parser.print_help()
            sys.exit(1)
        else:
            self.aws_profile = str(self.args.awsprofile)

        if self.args.awsregion is None:
            print('An AWS Region is required')
            self.parser.print_help()
            sys.exit(1)
        else:
            self.aws_region = self.args.awsregion

        if self.args.env is None:
            print('An Environment must be specified')
            sys.exit(1)
        else:
            self.environment = self.args.env
            try:
                self.valid_env.index(self.environment)
            except ValueError:
                print(f'Invalid Region {self.environment}')
                self.parser.print_help()
                sys.exit(1)

        if self.args.stacknamebase is None:
            print('A base name  for the stacks is required')
            sys.exit(1)
        else:
            self.stackname_base = self.args.stacknamebase
            if any(x in self.stackname_base for x in self.illegal_characters):
                print('bad characters in Base Name, only alphanumeric and dash are allowed. ')
                exit(2)
            if len(self.environment + "-" + self.stackname_base + "-" + self.aws_region) > 50:
                print(f'Consider choosing a stack name with less characters. '
                      f'The Roles Stack creates to named roles which cannot be '
                      f'longer than 64 characters. The RoleName will include the '
                      f'region and the specific role identifier. '
                      f'Your current stack name potential is {len(self.environment + "-" + self.stackname_base + "-" + self.aws_region)} characters long. '
                      f'50 chapters is a more acceptable amount')
                exit(2)

        return self.aws_profile, self.aws_region, self.environment, self.stackname_base, self.first_stack

    def search_exports(self, session, export_name, stack_name):
        self.export_value = None
        self.cloudform_client = session.client('cloudformation')
        self.cf_exports = self.cloudform_client.list_exports()
        x = 0
        while x < len(self.cf_exports['Exports']):
            self.exporting_stack_id = self.cf_exports['Exports'][x]['ExportingStackId']
            if self.exporting_stack_id.find(stack_name) > 0:
                if self.cf_exports['Exports'][x]['Name'] and \
                        self.cf_exports['Exports'][x]['Name'] == stack_name + ":" + export_name:
                    self.export_value = self.cf_exports['Exports'][x]['Value']
                    break
            x += 1
            try:
                if len(self.cf_exports['NextToken']) > 0 and x == len(self.cf_exports['Exports']):
                    x = 0
                    self.cf_exports = self.cloudform_client.list_exports(NextToken=self.cf_exports['NextToken'])
            except KeyError as e:
                pass
        return self.export_value