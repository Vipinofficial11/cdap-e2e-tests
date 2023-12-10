# Copyright © 2023 Cask Data, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at

# http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

import io
import os
import requests
import subprocess
import zipfile
import shutil
import argparse
import urllib.request
import yaml

def run_shell_command(cmd):
    process = subprocess.run(cmd.split(" "), stderr=subprocess.PIPE)
    if process.returncode != 0:
        print("Process completed with error: ", process.stderr)
    assert process.returncode == 0

# Parse command line optional arguments
parser=argparse.ArgumentParser()
parser.add_argument('--testRunner', help='TestRunner class to execute tests')
args=parser.parse_args()

# Start CDAP sandbox
# print("Downloading CDAP sandbox")
# sandbox_url = "https://github.com/cdapio/cdap-build/releases/download/latest/cdap-sandbox-6.11.0-SNAPSHOT.zip"
# sandbox_dir = sandbox_url.split("/")[-1].split(".zip")[0]
# r = requests.get(sandbox_url)
# z = zipfile.ZipFile(io.BytesIO(r.content))
# z.extractall("./sandbox")

print("Building CDAP Sandbox")
os.chdir("./plugin")
run_shell_command("git submodule update --init --recursive --remote")
run_shell_command("mvn clean install -DskipTests")
my_env = os.environ.copy()
my_env["MAVEN_OPTS"] = "-Xmx1024m -XX:MaxPermSize=128m"
run_shell_command('mvn clean package -pl cdap-standalone,cdap-app-templates/cdap-etl -am -amd -DskipTests -P '
                  'templates,dist,release,unit-tests')
os.chdir("./cdap-standalone/target")

sandbox = "cdap-sandbox-6.11.0-SNAPSHOT.zip"
print("cwd before extracting :", os.getcwd())
with zipfile.ZipFile(sandbox, 'r') as z:
    z.extractall(os.getcwd())

os.chdir("./cdap-sandbox-6.11.0-SNAPSHOT/bin")

print("COMPLETED TILL BUILDING THE ZIP FILE FOR SANDBOX")
my_env["_JAVA_OPTIONS"] = "-Xmx32G"
process = subprocess.Popen("./cdap sandbox start", shell=True, env=my_env)
process.communicate()
assert process.returncode == 0

# print("Installing gcs connector jar")
# gcs_jar_url = "https://storage.googleapis.com/hadoop-lib/gcs/gcs-connector-hadoop2-2.2.16.jar"
# gcs_jar_fname = f"sandbox/{sandbox_dir}/lib/gcs-connector-hadoop2-2.2.9.jar"
# urllib.request.urlretrieve(gcs_jar_url, gcs_jar_fname)
#
# print("Start the sandbox")
# run_shell_command(f"chmod +x sandbox/{sandbox_dir}/bin/cdap")
# my_env = os.environ.copy()
# my_env["_JAVA_OPTIONS"] = "-Xmx32G"
# sandbox_start_cmd = "sandbox/" + sandbox_dir + "/bin/cdap sandbox restart"
# process = subprocess.Popen(sandbox_start_cmd, shell=True, env=my_env)
# process.communicate()
# assert process.returncode == 0
#
# Setting the task executor memory
res = requests.put('http://localhost:11015/v3/preferences', headers= {'Content-Type': 'application/json'}, json={'task.executor.system.resources.memory': 4096})
assert res.ok or print(res.text)

# Upload required plugins from CDAP Hub
plugin_details_file = open(os.path.join('e2e', 'src', 'main', 'scripts', 'required_plugins.yaml'))
plugin_details = yaml.load(plugin_details_file, Loader=yaml.FullLoader)

for plugin, details in plugin_details['plugins'].items():
    artifact_name = details.get('artifact_name')
    artifact_version = details.get('artifact_version')
    subprocess.run(["python3.9", os.path.join('e2e', 'src', 'main', 'scripts', 'upload_required_plugins.py'), artifact_name, artifact_version])


# Run e2e tests
print("Running e2e integration tests for cdap")

testrunner_to_run = ""
if args.testRunner:
    testrunner_to_run = args.testRunner

assertion_error = None
try:
    os.chdir("./plugin/cdap-e2e-tests")
    if testrunner_to_run:
        print("TestRunner to run : " + testrunner_to_run)
        run_shell_command(f"mvn verify -P e2e-tests -DTEST_RUNNER={testrunner_to_run}")
    else:
        run_shell_command(f"mvn verify -P e2e-test")
except AssertionError as e:
    assertion_error = e
finally:
    os.chdir("../..")

cwd = os.getcwd()
print("Copying sandbox logs to e2e-debug")
shutil.copytree(cwd+"/sandbox/"+sandbox_dir+"/data/logs", cwd+"/plugin/target/cdap-e2e-tests/e2e-debug/sandbox/data/logs")
shutil.copytree(cwd+"/sandbox/"+sandbox_dir+"/logs", cwd+"/plugin/cdap-e2e-tests/target/e2e-debug/sandbox/logs")
if assertion_error != None:
    raise assertion_error