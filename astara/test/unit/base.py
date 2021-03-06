# Copyright 2015 Akanda, Inc.
#
# Author: Akanda, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


import mock
import testtools

from oslo_config import cfg
from oslo_config import fixture as config_fixture


class RugTestBase(testtools.TestCase):
    def setUp(self):
        super(RugTestBase, self).setUp()
        self.test_config = self.useFixture(config_fixture.Config(cfg.CONF))
        self.argv = []
        cfg.CONF.import_opt('host', 'astara.main')

        self.time_patch = mock.patch('time.sleep')
        self.time_mock = self.time_patch.start()
        self.addCleanup(mock.patch.stopall)

    def config(self, **kw):
        """Override config options for a test."""
        group = kw.pop('group', None)
        for k, v in kw.items():
            cfg.CONF.set_override(k, v, group)
