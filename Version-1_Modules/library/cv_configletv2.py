#!/usr/bin/env python
#
# Copyright (c) 2019, Arista Networks EOS+
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#   Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
#
#   Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
#
#   Neither the name of Arista Networks nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# 'AS IS' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL ARISTA NETWORKS
# BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
# BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN
# IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
DOCUMENTATION = """
---
module: cv_configlet
version_added: "2.2"
author: "EMEA AS (ansible-dev@arista.com)"
short_description: Create, Delete, or Update CloudVision Portal Configlets.
description:
  - CloudVison Portal Configlet compares the list of configlets and config in
  in configlets against cvp-facts then adds, deletes, or updates them as appropriate.
  If a configlet is in cvp_facts but not in configlets it will be deleted
  If a configlet is in configlets but not in cvp_facts it will be created
  If a configlet is in both configlets and cvp_facts it configuration will be compared
  and updated with the version in configlets if the two are different.
"""
# Required by Ansible and CVP
from ansible.module_utils.basic import AnsibleModule
from cvprac.cvp_client import CvpClient
from cvprac.cvp_client_errors import CvpLoginError, CvpApiError
# Required by compare function
import difflib
from fuzzywuzzy import fuzz # Library that uses Levenshtein Distance to calculate the differences between strings.

def compare(fromText, toText, lines=10):
    """ Compare text string in 'fromText' with 'toText' and produce
        diffRatio - a score as a float in the range [0, 1] 2.0*M / T
          T is the total number of elements in both sequences,
          M is the number of matches.
          Score - 1.0 if the sequences are identical, and 0.0 if they have nothing in common.
        unified diff list
          Code	Meaning
          '- '	line unique to sequence 1
          '+ '	line unique to sequence 2
          '  '	line common to both sequences
          '? '	line not present in either input sequence
    """
    fromlines = fromText.splitlines(1)
    tolines = toText.splitlines(1)
    diff = list(difflib.unified_diff(fromlines, tolines,n=lines))
    textComp = difflib.SequenceMatcher(None, fromText, toText)
    diffRatio = round( textComp.quick_ratio()*100, 2)
    return [diffRatio,diff]

def connect(module):
    ''' Connects to CVP device using user provided credentials from playbook.
    :param module: Ansible module with parameters and client connection.
    :return: CvpClient object with connection instantiated.
    '''
    client = CvpClient()
    try:
        client.connect([module.params['host']],
                       module.params['username'],
                       module.params['password'],
                       protocol=module.params['protocol'],
                       port=module.params['port'],
                       )
    except CvpLoginError, e:
        module.fail_json(msg=str(e))
    return client

def configlet_action(module):
    ''' Compare configlets in "configlets" with configlets in "cvp_facts"
    if configlet exists in "cvp_facts" check config, if changed update
    if configlet does not exist in "cvp_facts" add to CVP
    if configlet in "cvp_facts" but not in "configlets" remove from CVP if
    not applied to a device or container.
    :param module: Ansible module with parameters and client connection.
    :return: data: dict of module actions and taskIDs
    '''
    # If any configlet changed updated 'changed' flag
    changed = False
    #Compare configlets against cvp_facts-configlets
    keep_configlet = [] # configlets with no changes
    delete_configlet = [] # configlets to delete from CVP
    deleted = []
    update_configlet = [] # configlets with config changes
    updated = []
    new_configlet = [] # configlets to add to CVP
    new = []

    for configlet in module.params['cvp_facts']['configlets']:
        if configlet['name'] in module.params['configlets']:
            ansible_configlet = module.params['configlets'][configlet['name']]
            configlet_compare = compare(configlet['config'],ansible_configlet)
            if configlet_compare[0] == 1:
                keep_configlet.append(configlet)
            else:
                update_configlet.append({'data':configlet,'config':ansible_configlet})
        else:
            delete_configlet.append(configlet)
    for configlet in module.params['configlets']:
        if str(configlet) not in module.params['cvp_facts']['configlets']:
            new_configlet.append({'name':str(configlet),'config':configlet})

    # delete any configlets as required
    if len(delete_configlet) != 0:
        for configlet in delete_configlet:
            delete_resp =  module['client'].api.delete_configlet(configlet['name'], configlet['key'])
            if "errorMessage" in str(delete_resp):
                module.warn("Configlet %s cannot be delete - %s"
                            %(configlet['name'],delete_resp['errorMessage']))
            else:
                changed = True
                deleted.append(configlet['name'])

    # Update any configlets as required
    if len(update_configlet) != 0:
        for configlet in update_configlet:
            update_resp = module['client'].api.update_configlet(configlet['config'],
                                                                configlet['data']['key'],
                                                                configlet['data']['name'])
            if "errorMessage" in str(update_resp):
                module.warn("Configlet %s cannot be updated - %s"
                            %(configlet['name'],update_resp['errorMessage']))
            else:
                module['client'].api.add_note_to_configlet(configlet['data']['key'],
                                                       "## Managed by Ansible ##")
                changed = True
                updated.append(configlet['name'])
                
    # Add any new configlets as required
    if len(new_configlet) != 0:
        for configlet in new_configlet:
            new_resp = module['client'].api.add_configlet(configlet['name'],configlet['config'])
            if "errorMessage" in str(new_resp):
                module.warn("Configlet %s cannot be created - %s"
                            %(configlet['name'],new_resp['errorMessage']))
            else:
                module['client'].api.add_note_to_configlet(new_resp,
                                                       "## Managed by Ansible ##")
                changed = True
                new.append(configlet['name'])

    # Get any Pending Tasks in CVP
    if changed:
        tasks = module['client'].api.get_tasks_by_status('Pending'):

    data = {'new':new,'updated':updated,'deleted':deleted,'tasks':tasks}
    return [changed,data]


def main():
    """ main entry point for module execution
    """
    argument_spec = dict(
        host=dict(required=True),
        port=dict(type='int', default=None),
        protocol=dict(default='https', choices=['http', 'https']),
        username=dict(required=True),
        password=dict(required=True),
        configlets=dict(type='list',required=True),
        cvp_facts=dict(type='dict',required=True)
        )

    module = AnsibleModule(argument_spec=argument_spec,
                           supports_check_mode=False)
    result = dict(changed=False)
    messages = dict(issues=False)
    # Connect to CVP instance
    module.client = connect(module)
    
    # Pass module params to configlet_action to act on configlet
    result = configlet_action(module)
    module.exit_json(**result)


if __name__ == '__main__':
    main()
