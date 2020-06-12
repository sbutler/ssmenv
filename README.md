SSM Environment File
====================

This script takes a parent path in SSM Parameter Store, lists all the parameters,
and builds an environment file from it. You can then use this file to pass
variables to your main docker container.

The environment variable file is build using this process:

1. Loop over all the SSM Parameter Store values present under a particular path.
2. Take the name of the environment variable from the last path component. For
    example, if the path is `/my-app/environment/FOO` then the variable name will
    be `FOO`. If the last path component name is not a valid bash variable name
    (starts with "a-z", "A-Z", or "\_" and only contains "a-z", "A-Z", "0-9", and
    "\_") then it will be skipped.
3. Quote the value of the parameter based on the style. See the style option for
    how this works.
4. Write the `name=value` to the output file. It will also output a comment
    letting you know where that variable came from for debugging purposes.

Configuration
-------------

Configuration in docker situations is mostly done with environment variables.
If you are running it yourself then you can also use command line arguments. If
a value is present in both the environment and the command line then the command
line is used.

### AWS SDK

- Environment: `AWS_REGION`, `AWS_PROFILE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, etc

The AWS SDK takes its configuration from the environemnt. The minimum configuration
is to specify the region using `AWS_REGION`. The rest of the configuration depends
on your environment.

**If you are using roles (EC2 Instance Role, ECS Task Role) then do not specify
any other variables.** The AWS SDK will automatically detect EC2 Instance and
ECS Task roles! Specifying other variables is unncessary and will probably cause
the AWS SDK to not operate correctly.

If you have run `aws configure` and want to use those credentials then you also
do not need to specify any other variables. If you have different client
profiles then you can use `AWS_PROFILE` to select the correct one.

**This is the least recommended way to pass credentials:** if you have an IAM
User with an access key and secret key then you can specify those in
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.

### Output

- Environemnt: `OUTPUT`
- Command Line: `--output`, `-o`

Specifies the file to write to. The docker image sets a default of `/ssmenv/environment`
but the script itself uses a default of `/dev/stdout`.

### Recursive

- Environemnt: `RECURSIVE`
- Command Line: `--recurse`, `-r`

When walking the SSM Parameter Store paths, whether to recurse the heirachy or
only process a single level. The default is to not recurse.

### Style

- Environment: `STYLE`
- Command Line: `--style`, `-s`

What style to write to the output file. There are three value values:

- `dotenv`: this is a style appropriate for the Python or NodeJS dotenv library.
    Shell metacharacters in the values are escaped and the value is quoted if
    needed.
- `bash`: this is the same style as `dotenv` (and is compatible with those libraries),
    but includes the `export` keyword so that it can be sourced as a bash script.
- `docker`: this is a style that can be used with the `--environmentFile` argument
    of docker commands. The shell metacharacters in the values are **not** escaped
    so do not use this style with dotenv or bash.

The choice of style is important for how you plan on using the output. The default
is to do dotenv.

### Verbose

- Environment: not supported
- Command Line: `--verbose`, `-v`

This controls what level of logging for the script on stderr.

- None: only warnings and higher logs are reported.
- `-v`: informational and higher logs from the script.
- `-vv`: debug and higher logs from the script.
- `-vvv`: debug and higher logs from the script and included libraries.

### Parameters

- Environment: `PARAMETER`, `PARAMETER_*`
- Command Line: all positional (remaining) parameters

You can specify one or more SSM Parameter Store paths to get names and values
from. If you use the environment variables you can specify paths in any variable
that starts with `PARAMETER` (example: `PARAMETER`, `PARAMETER_common`,
`PARAMETER_app`, etc). If you use the command line then the paths are all the
renaming, non-named arguments to the command.

AWS Permissions
---------------

This script uses `ssm:GetParametersByPath`. Additionally, if you have parameters
protected by an AWS KMS CMK then you will need to add permissions to use that
key to decrypt. AWS says `kms:Decrypt` is sufficient but you might need to add
more permissions.

Usage
-----

This was designed to be run in ECS as a dependent container before the main
container. You do this by specifying `dependsOn` in the main container
specification. For example:

```json
[
    {
        "name": "my-app",
        "dependsOn": [
            { "containerName": "ssmenv", "condition": "SUCCESS" }
        ],
        "mountPoints": [
            { "sourceVolume": "ssmenv", "containerPath": "/ssmenv", "readOnly": true },
            ...
        ],
        "essential": true
        ...
    },
    {
        "name": "ssmenv",
        "image": "sbutler/ssmenv:latest",
        "environment": [
            { "name": "AWS_REGION", "value": "us-east-2" },
            { "name": "STYLE", "value": "bash" },
            { "name": "PARAMETER", "value": "/my-app/environment/" },
            ...
        ],
        "mountPoints": [
            { "sourceVolume": "ssmenv", "containerPath": "/ssmenv", "readOnly": false },
        ],
        "essential": false
    }
]
```

You need to have a volume named "ssmenv" in your task definition. This setup
for containers will run the "ssmenv" container to completion first, which
outputs a bash style environment file, and then starts the "my-app" container.
How you use the environment file in your "my-app" container varies.

- `dotenv` command: if you have the python dotenv library installed then it
    comes with a `dotenv` command you can use to run your main app. This is
    done by overriding the container default command with
    `[ "dotenv", "--file=/ssmenv/environment", "my-app-command" ]`.
- `dotenv` library: if you add support to your app then you can tell it to load
    the dotenv file itself. This depends on how you choose to modify the app.
- bash script: you can wrap your app command in a simple bash script that first
    loads the environment. This is done by overriding the container default
    command with: `[ "bash", "-c", ". /ssmenv/environment; exec my-app-command" ]`.
