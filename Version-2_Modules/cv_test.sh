#!/bin/sh
verbose=""
echo 'Ansible Test -  cv_facts and cv_configlets..'
while getopts "v:" option; do
case "${option}" in
v)
  case $OPTARG in
  0)
  ansible-playbook -i /etc/ansible/hosts cv_test.yml;;
  1)
  ansible-playbook -v /etc/ansible/hosts cv_test.yml;;
  2)
  ansible-playbook -vv /etc/ansible/hosts cv_test.yml;;
  3)
  ansible-playbook -vvv /etc/ansible/hosts cv_test.yml;;
  esac;;
esac
done
echo 'Ansible Test - Complete'
