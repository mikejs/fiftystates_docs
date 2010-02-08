from fabric.api import *
from fabric.contrib.project import *

env.hosts = ['fsec2']

def build():
    local('make html')

def deploy():
    build()
    rsync_project(remote_dir='~/', local_dir='_build/html')
    sudo('rm -rf /home/fiftystates/data/html')
    sudo('mv /home/mike/html /home/fiftystates/data/')
    sudo('chown -R fiftystates:www-data /home/fiftystates/data/html')
