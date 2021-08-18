import boto3
import json
from datetime import datetime, timedelta, date
from dateutil.tz import tzutc
import re
from pprint import pprint
import os, sys
import argparse
import csv
region = 'ap-southeast-2'

this_account_id = boto3.client('sts').get_caller_identity().get('Account')
this_account_alias = boto3.client('iam').list_account_aliases()['AccountAliases'][0]

print("___________________")
print("\t" + region)
print("\n        You are looking at the account backups on account number: " + this_account_id + " for " + this_account_alias + ". Region is set to: " + region)
print("___________________\n")

sns = boto3.client('sns', region_name=region)
# pull data from aws
def call_aws_ec2():
    ec2client = boto3.client("ec2", region_name=region)
    all_response = ec2client.describe_instances()
    return all_response

def call_aws_snapshots():
    snapshotclient = boto3.client("ec2", region_name=region)
    snapshots = snapshotclient.describe_snapshots(Filters=[{
            'Name': 'owner-id',
            'Values': [
                this_account_id
            ]
        }])
    return snapshots

def call_aws_asg():
    autoscaling = boto3.client("autoscaling", region_name=region)
    asg_response = autoscaling.describe_auto_scaling_instances()
    return asg_response

def call_aws_vols():
    volumes = boto3.client("ec2", region_name=region).describe_volumes()
    return volumes

# create a list of ec2 instances
def call_list_instances(ec2, asg, vols, snaps): 
    instance_names = []
    for reservation in ec2["Reservations"]:
        for instance in reservation["Instances"]:
            instance_tag = ['']
            instance_state = instance["State"]["Name"]
            for tag in instance['Tags']:
                if tag['Key'] == 'DailyBackup':
                    instance_tag=["Daily Backup"]
                else:
                    continue
            vol = []
            for volume in instance["BlockDeviceMappings"]:
                volid = volume['Ebs']['VolumeId']
                vol.append(volid)
                for v in vols['Volumes']:
                    try:
                        if v['Attachments'][0]['VolumeId'] == volid:
                            tagFound = False
                            if v['Tags']:
                                for tag in v['Tags']:
                                    if tag['Key'] == 'cmd:backup':
                                        vol.append(tag['Value'])
                                        tagFound = True
                            if not tagFound:
                                vol.append("No Volume backup tag")
                    except(IndexError, KeyError):
                        vol.append("No Tag")
                    except([]):
                        vol.append("No Attachments in Volumes")
                text = ""
                for snap in snaps['Snapshots']:
                    if snap['StartTime'].date() >= (date.today() - timedelta(days=7)):
                        if snap['VolumeId'] == volid:
                            text = f"{text}{snap['SnapshotId'][:10]},"
                            text += f"{snap['StartTime'].strftime('%m-%d')}"
                            text += f" "
                vol.append(text)
            asgid = []
            for inst in asg["AutoScalingInstances"]:
                asgid = inst["InstanceId"]
                if asgid == instance['InstanceId']:
                    vol.insert(2,'------This instance is an ASG------')

            instance_name=''
            for nametag in instance.get('Tags', []):
                if nametag['Key'] != 'Name':
                    continue
                instance_name=nametag['Value']
            instance_names.append([instance['InstanceId'], instance_tag[0], instance_state, instance_name, vol])

    table = list()
    if len(instance_names) > 0:
        x = this_account_id + " - "
        x += this_account_alias 
        x += " - Please review this list of instances with backups, and ensure 7 days of backups.\n"
        print(" #               ID                          Tag                  State             Name")
        x += " #               ID                                   Tag                         State                   Name\n"
        table.append(x)
        instance_names.sort(key=lambda x: x[2])
        for count, i in enumerate(instance_names, 1):
            a, b, c, d, e = [i][0]
            vol = ''
            for i, j, k in zip(*[iter(e)] * 3):
                vol = vol + ("|" + i + "| " + j + " | " + k + "|\n")
                # Number, InstanceId, InstanceBackupTag, Running, InstanceName, VolumeList
            print(       "\n{:^4}\t{:}\t\t{:20}\t{:}\t\t{:}\n\n{:}".format(count, a, b, c, d, vol))
            table.append("\n{:^4}\t{:}\t\t{:20}\t{:}\t\t{:}\n\n{:}".format(count, a, b, c, d, vol))
    else:
        print("No instances in selected region")

    return table

def lambda_handler(event, context):
    
    ec2 = call_aws_ec2()
    asg = call_aws_asg()
    vols = call_aws_vols()
    snaps = call_aws_snapshots()
    table = call_list_instances(ec2, asg, vols, snaps)
    message = "".join(table)
    # Publish a simple message to the specified SNS topic
    topic_name = os.getenv('TOPICNAME') # replace as needed
    topic_arn = os.getenv('TOPICARN')
    response = sns.publish(
        TopicArn=topic_arn,   
        Message=message, 
        Subject="[{acc_alias}] - [{acc_id}] - [{acc_region}] - BackupChecker".format(acc_alias=this_account_alias, acc_id=this_account_id, acc_region=region)
    )
    return { 
        'message' : "Done"
    }  
########### Uncomment to run locally from your laptop>
if __name__ == "__main__":
    lambda_handler({},{})


