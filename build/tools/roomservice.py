#!/usr/bin/env python
# Copyright (C) 2012-2013, The CyanogenMod Project
#           (C) 2017-2018,2020-2021, The LineageOS Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function

import base64
import json
import netrc
import os
import re
import sys
try:
  # For python3
  import urllib.error
  import urllib.parse
  import urllib.request
except ImportError:
  # For python2
  import imp
  import urllib2
  import urlparse
  urllib = imp.new_module('urllib')
  urllib.error = urllib2
  urllib.parse = urlparse
  urllib.request = urllib2

from xml.etree import ElementTree

product = sys.argv[1]

depsonly = sys.argv[2] if len(sys.argv) > 2 else None
try:
    device = product[product.index("_") + 1:]
except:
    device = product

if not depsonly:
  print(
      f"Device {device} not found. Attempting to retrieve device repository from LineageOS Github (http://github.com/LineageOS)."
  )

repositories = []

try:
  if authtuple := netrc.netrc().authenticators("api.github.com"):
    auth_string = f'{authtuple[0]}:{authtuple[2]}'.encode()
    githubauth = base64.encodestring(auth_string).decode().replace('\n', '')
  else:
    githubauth = None
except:
    githubauth = None

def add_auth(githubreq):
  if githubauth:
    githubreq.add_header("Authorization", f"Basic {githubauth}")

if not depsonly:
  githubreq = urllib.request.Request(
      f"https://api.github.com/search/repositories?q={device}+user:LineageOS+in:name+fork:true"
  )
  add_auth(githubreq)
  try:
      result = json.loads(urllib.request.urlopen(githubreq).read().decode())
  except urllib.error.URLError:
      print("Failed to search GitHub")
      sys.exit(1)
  except ValueError:
      print("Failed to parse return data from GitHub")
      sys.exit(1)
  for res in result.get('items', []):
      repositories.append(res)

local_manifests = r'.repo/local_manifests'
if not os.path.exists(local_manifests): os.makedirs(local_manifests)

def exists_in_tree(lm, path):
  return any(child.attrib['path'] == path for child in lm.getchildren())

# in-place prettyprint formatter
def indent(elem, level=0):
  i = "\n" + level*"  "
  if len(elem):
    if not elem.text or not elem.text.strip():
      elem.text = f"{i}  "
    if not elem.tail or not elem.tail.strip():
        elem.tail = i
    for elem in elem:
        indent(elem, level+1)
    if not elem.tail or not elem.tail.strip():
        elem.tail = i
  elif level and (not elem.tail or not elem.tail.strip()):
    elem.tail = i

def get_manifest_path():
  '''Find the current manifest path
    In old versions of repo this is at .repo/manifest.xml
    In new versions, .repo/manifest.xml includes an include
    to some arbitrary file in .repo/manifests'''

  m = ElementTree.parse(".repo/manifest.xml")
  try:
    m.findall('default')[0]
    return '.repo/manifest.xml'
  except IndexError:
    return f'.repo/manifests/{m.find("include").get("name")}'

def get_default_revision():
    m = ElementTree.parse(get_manifest_path())
    d = m.findall('default')[0]
    r = d.get('revision')
    return r.replace('refs/heads/', '').replace('refs/tags/', '')

def get_from_manifest(devicename):
  try:
      lm = ElementTree.parse(".repo/local_manifests/roomservice.xml")
      lm = lm.getroot()
  except:
      lm = ElementTree.Element("manifest")

  return next(
      (localpath.get("path") for localpath in lm.findall("project")
       if re.search(f"android_device_.*_{device}$", localpath.get("name"))),
      None,
  )

def is_in_manifest(projectpath):
  try:
      lm = ElementTree.parse(".repo/local_manifests/roomservice.xml")
      lm = lm.getroot()
  except:
      lm = ElementTree.Element("manifest")

  for localpath in lm.findall("project"):
      if localpath.get("path") == projectpath:
          return True

  # Search in main manifest, too
  try:
      lm = ElementTree.parse(get_manifest_path())
      lm = lm.getroot()
  except:
      lm = ElementTree.Element("manifest")

  for localpath in lm.findall("project"):
      if localpath.get("path") == projectpath:
          return True

  # ... and don't forget the lineage snippet
  try:
      lm = ElementTree.parse(".repo/manifests/snippets/lineage.xml")
      lm = lm.getroot()
  except:
      lm = ElementTree.Element("manifest")

  return any(
      localpath.get("path") == projectpath
      for localpath in lm.findall("project"))

def add_to_manifest(repositories, fallback_branch = None):
  try:
      lm = ElementTree.parse(".repo/local_manifests/roomservice.xml")
      lm = lm.getroot()
  except:
      lm = ElementTree.Element("manifest")

  for repository in repositories:
    repo_name = repository['repository']
    repo_target = repository['target_path']
    print(f'Checking if {repo_target} is fetched from {repo_name}')
    if is_in_manifest(repo_target):
      print(f'LineageOS/{repo_name} already fetched to {repo_target}')
      continue

    print(f'Adding dependency: LineageOS/{repo_name} -> {repo_target}')
    project = ElementTree.Element(
        "project",
        attrib={
            "path": repo_target,
            "remote": "github",
            "name": f"LineageOS/{repo_name}",
        },
    )

    if 'branch' in repository:
      project.set('revision',repository['branch'])
    elif fallback_branch:
      print(f"Using fallback branch {fallback_branch} for {repo_name}")
      project.set('revision', fallback_branch)
    else:
      print(f"Using default branch for {repo_name}")

    lm.append(project)

  indent(lm, 0)
  raw_xml = ElementTree.tostring(lm).decode()
  raw_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + raw_xml

  with open('.repo/local_manifests/roomservice.xml', 'w') as f:
    f.write(raw_xml)

def fetch_dependencies(repo_path, fallback_branch = None):
  print(f'Looking for dependencies in {repo_path}')
  dependencies_path = f'{repo_path}/lineage.dependencies'
  syncable_repos = []
  verify_repos = []

  if os.path.exists(dependencies_path):
    with open(dependencies_path, 'r') as dependencies_file:
      dependencies = json.loads(dependencies_file.read())
      fetch_list = []

      for dependency in dependencies:
        if not is_in_manifest(dependency['target_path']):
          fetch_list.append(dependency)
          syncable_repos.append(dependency['target_path'])
        verify_repos.append(dependency['target_path'])
        if not os.path.isdir(dependency['target_path']):
            syncable_repos.append(dependency['target_path'])

    if fetch_list:
      print('Adding dependencies to manifest')
      add_to_manifest(fetch_list, fallback_branch)
  else:
    print(f'{repo_path} has no additional dependencies.')

  if syncable_repos:
    print('Syncing dependencies')
    os.system(f"repo sync --force-sync {' '.join(syncable_repos)}")

  for deprepo in verify_repos:
      fetch_dependencies(deprepo)

def has_branch(branches, revision):
    return revision in [branch['name'] for branch in branches]

if depsonly:
  if repo_path := get_from_manifest(device):
    fetch_dependencies(repo_path)
  else:
    print("Trying dependencies-only mode on a non-existing device tree?")

  sys.exit()

else:
  for repository in repositories:
    repo_name = repository['name']
    if re.match(f"^android_device_[^_]*_{device}$", repo_name):
      print(f"Found repository: {repository['name']}")

      manufacturer = repo_name.replace("android_device_", "").replace("_" + device, "")

      default_revision = get_default_revision()
      print(f"Default revision: {default_revision}")
      print("Checking branch info")
      githubreq = urllib.request.Request(repository['branches_url'].replace('{/branch}', ''))
      add_auth(githubreq)
      result = json.loads(urllib.request.urlopen(githubreq).read().decode())

      ## Try tags, too, since that's what releases use
      if not has_branch(result, default_revision):
          githubreq = urllib.request.Request(repository['tags_url'].replace('{/tag}', ''))
          add_auth(githubreq)
          result.extend (json.loads(urllib.request.urlopen(githubreq).read().decode()))

      repo_path = f"device/{manufacturer}/{device}"
      adding = {'repository':repo_name,'target_path':repo_path}

      fallback_branch = None
      if not has_branch(result, default_revision):
        if os.getenv('ROOMSERVICE_BRANCHES'):
          fallbacks = list(filter(bool, os.getenv('ROOMSERVICE_BRANCHES').split(' ')))
          for fallback in fallbacks:
            if has_branch(result, fallback):
              print(f"Using fallback branch: {fallback}")
              fallback_branch = fallback
              break

        if not fallback_branch:
          print(
              f"Default revision {default_revision} not found in {repo_name}. Bailing."
          )
          print("Branches found:")
          for branch in [branch['name'] for branch in result]:
              print(branch)
          print("Use the ROOMSERVICE_BRANCHES environment variable to specify a list of fallback branches.")
          sys.exit()

      add_to_manifest([adding], fallback_branch)

      print("Syncing repository to retrieve project.")
      os.system(f'repo sync --force-sync {repo_path}')
      print("Repository synced!")

      fetch_dependencies(repo_path, fallback_branch)
      print("Done")
      sys.exit()

print(
    f"Repository for {device} not found in the LineageOS Github repository list. If this is in error, you may need to manually add it to your local_manifests/roomservice.xml."
)
