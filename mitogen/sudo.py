# Copyright 2017, David Wilson
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
# may be used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import logging
import optparse
import os
import time

import mitogen.core
import mitogen.parent
from mitogen.core import b


LOG = logging.getLogger(__name__)
PASSWORD_PROMPT = b('password')
SUDO_OPTIONS = [
    #(False, 'bool', '--askpass', '-A')
    #(False, 'str', '--auth-type', '-a')
    #(False, 'bool', '--background', '-b')
    #(False, 'str', '--close-from', '-C')
    #(False, 'str', '--login-class', 'c')
    (True,  'bool', '--preserve-env', '-E'),
    #(False, 'bool', '--edit', '-e')
    #(False, 'str', '--group', '-g')
    (True,  'bool', '--set-home', '-H'),
    #(False, 'str', '--host', '-h')
    (False, 'bool', '--login', '-i'),
    #(False, 'bool', '--remove-timestamp', '-K')
    #(False, 'bool', '--reset-timestamp', '-k')
    #(False, 'bool', '--list', '-l')
    #(False, 'bool', '--preserve-groups', '-P')
    #(False, 'str', '--prompt', '-p')

    # SELinux options. Passed through as-is.
    (False, 'str', '--role', '-r'),
    (False, 'str', '--type', '-t'),

    # These options are supplied by default by Ansible, but are ignored, as
    # sudo always runs under a TTY with Mitogen.
    (True, 'bool', '--stdin', '-S'),
    (True, 'bool', '--non-interactive', '-n'),

    #(False, 'str', '--shell', '-s')
    #(False, 'str', '--other-user', '-U')
    (False, 'str', '--user', '-u'),
    #(False, 'bool', '--version', '-V')
    #(False, 'bool', '--validate', '-v')
]


class OptionParser(optparse.OptionParser):
    def help(self):
        self.exit()
    def error(self, msg):
        self.exit(msg=msg)
    def exit(self, status=0, msg=None):
        msg = 'sudo: ' + (msg or 'unsupported option')
        raise mitogen.core.StreamError(msg)


def make_sudo_parser():
    parser = OptionParser()
    for supported, kind, longopt, shortopt in SUDO_OPTIONS:
        if kind == 'bool':
            parser.add_option(longopt, shortopt, action='store_true')
        else:
            parser.add_option(longopt, shortopt)
    return parser


def parse_sudo_flags(args):
    parser = make_sudo_parser()
    opts, args = parser.parse_args(args)
    if len(args):
        raise mitogen.core.StreamError('unsupported sudo arguments:'+str(args))
    return opts


class PasswordError(mitogen.core.StreamError):
    pass


def option(default, *args):
    for arg in args:
        if arg is not None:
            return arg
    return default


class Stream(mitogen.parent.Stream):
    create_child = staticmethod(mitogen.parent.tty_create_child)
    child_is_immediate_subprocess = False

    #: Once connected, points to the corresponding DiagLogStream, allowing it to
    #: be disconnected at the same time this stream is being torn down.
    tty_stream = None

    sudo_path = 'sudo'
    username = 'root'
    password = None
    preserve_env = False
    set_home = False
    login = False

    selinux_role = None
    selinux_type = None

    def construct(self, username=None, sudo_path=None, password=None,
                  preserve_env=None, set_home=None, sudo_args=None,
                  login=None, selinux_role=None, selinux_type=None, **kwargs):
        super(Stream, self).construct(**kwargs)
        opts = parse_sudo_flags(sudo_args or [])

        self.username = option(self.username, username, opts.user)
        self.sudo_path = option(self.sudo_path, sudo_path)
        self.password = password or None
        self.preserve_env = option(self.preserve_env,
            preserve_env, opts.preserve_env)
        self.set_home = option(self.set_home, set_home, opts.set_home)
        self.login = option(self.login, login, opts.login)
        self.selinux_role = option(self.selinux_role, selinux_role, opts.role)
        self.selinux_type = option(self.selinux_type, selinux_type, opts.type)

    def connect(self):
        super(Stream, self).connect()
        self.name = u'sudo.' + mitogen.core.to_text(self.username)

    def on_disconnect(self, broker):
        self.tty_stream.on_disconnect(broker)
        super(Stream, self).on_disconnect(broker)

    def get_boot_command(self):
        # Note: sudo did not introduce long-format option processing until July
        # 2013, so even though we parse long-format options, supply short-form
        # to the sudo command.
        bits = [self.sudo_path, '-u', self.username]
        if self.preserve_env:
            bits += ['-E']
        if self.set_home:
            bits += ['-H']
        if self.login:
            bits += ['-i']
        if self.selinux_role:
            bits += ['-r', self.selinux_role]
        if self.selinux_type:
            bits += ['-t', self.selinux_type]

        bits = bits + ['--'] + super(Stream, self).get_boot_command()
        LOG.debug('sudo command line: %r', bits)
        return bits

    password_incorrect_msg = 'sudo password is incorrect'
    password_required_msg = 'sudo password is required'

    def _connect_bootstrap(self, extra_fd):
        if extra_fd:
            self.tty_stream = mitogen.parent.DiagLogStream(extra_fd, self)

        password_sent = False
        it = mitogen.parent.iter_read(
            fds=[self.receive_side.fd],
            deadline=self.connect_deadline,
        )

        for buf in it:
            LOG.debug('%r: received %r', self, buf)
            if buf.endswith(self.EC0_MARKER):
                self._ec0_received()
                return
            elif PASSWORD_PROMPT in buf.lower():
                if self.password is None:
                    raise PasswordError(self.password_required_msg)
                if password_sent:
                    raise PasswordError(self.password_incorrect_msg)
                self.receive_side.write(
                    mitogen.core.to_text(self.password + '\n').encode('utf-8')
                )
                password_sent = True
        raise mitogen.core.StreamError('bootstrap failed')
