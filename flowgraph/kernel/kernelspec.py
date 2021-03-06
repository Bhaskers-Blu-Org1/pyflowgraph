# Copyright 2018 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

""" Generate the kernel spec (JSON file).

XXX: Based on `ipykernel.kernelspec`. That is code is not modular enough to be
properly re-used. We resort to a monkey patch instead of a copy-and-paste.
"""
import sys

from ipykernel.kernelspec import make_ipkernel_cmd, InstallIPythonKernelSpecApp


def get_kernel_dict(extra_arguments=None):
    """ Construct dict for kernel.json.
    """
    mod = 'flowgraph.kernel'
    return {
        'argv': make_ipkernel_cmd(mod, extra_arguments=extra_arguments),
        'display_name': 'Python %i [flowgraph]' % sys.version_info[0],
        'language': 'python',
    }

def get_kernel_name():
    """ Get the (default) name for the kernel.
    """
    return 'flowgraph_python%i' % sys.version_info[0]


def main():
    # Monkey-patch!
    from ipykernel import kernelspec
    kernelspec.get_kernel_dict = get_kernel_dict
    kernelspec.KERNEL_NAME = get_kernel_name()
    
    InstallIPythonKernelSpecApp.launch_instance()


if __name__ == '__main__':
    main()
