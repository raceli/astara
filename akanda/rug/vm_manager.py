import netaddr
import time

from oslo.config import cfg

from akanda.rug.api import configuration
from akanda.rug.api import nova
from akanda.rug.api import quantum
from akanda.rug.api import akanda_client as router_api

DOWN = 'down'
UP = 'up'
CONFIGURED = 'configured'
RESTART = 'restart'


class VmManager(object):
    def __init__(self, router_id, log):
        self.router_id = router_id
        self.log = log
        self.state = DOWN
        self.router_obj = None
        self.quantum = quantum.Quantum(cfg.CONF)

        self.update_state(silent=True)

    def update_state(self, silent=False):
        self._ensure_cache()

        if self.router_obj.management_port is None:
            self.state = DOWN
            return self.state

        addr = _get_management_address(self.router_obj)
        for i in xrange(cfg.CONF.max_retries):
            if router_api.is_alive(addr, cfg.CONF.akanda_mgt_service_port):
                if self.state != CONFIGURED:
                    self.state = UP
                break
            if not silent:
                self.log.debug(
                    'Alive check failed. Attempt %d of %d',
                    i,
                    cfg.CONF.max_retries
                )
            time.sleep(cfg.CONF.retry_delay)
        else:
            self.state = DOWN

        return self.state

    def boot(self):
        # FIXME: Modify _ensure_cache() so we can call it with a force
        # flag instead of bypassing it.
        self.router_obj = self.quantum.get_router_detail(self.router_id)

        self._ensure_provider_ports(self.router_obj)

        self.log.info('Booting router')
        nova_client = nova.Nova(cfg.CONF)
        self.state = DOWN

        try:
            nova_client.reboot_router_instance(self.router_obj)
        except:
            self.log.exception('Router failed to start boot')
            return

        start = time.time()
        while time.time() - start < cfg.CONF.boot_timeout:
            if self.update_state(silent=True) in (UP, CONFIGURED):
                return
            self.log.debug('Router has not finished booting')

        self.log.error(
            'Router failed to boot within %d secs',
            cfg.CONF.boot_timeout)

    def stop(self):
        self._ensure_cache()
        self.log.info('Destroying router')

        nova_client = nova.Nova(cfg.CONF)
        nova_client.destroy_router_instance(self.router_obj)

        start = time.time()
        while time.time() - start < cfg.CONF.boot_timeout:
            if not nova_client.get_router_instance_status(self.router_obj):
                self.state = DOWN
                return
            self.log.debug('Router has not finished stopping')
            time.sleep(cfg.CONF.retry_delay)
        self.log.error(
            'Router failed to stop within %d secs',
            cfg.CONF.boot_timeout)

    def configure(self):
        self.log.debug('Begin router config')
        self.state = UP

        # FIXME: This might raise an error, which doesn't mean the
        # *router* is broken, but does mean we can't update it.
        # Change the exception to something the caller can catch
        # safely.
        self.router_obj = self.quantum.get_router_detail(self.router_id)

        addr = _get_management_address(self.router_obj)

        # FIXME: This should raise an explicit exception so the caller
        # knows that we could not talk to the router (versus the issue
        # above).
        interfaces = router_api.get_interfaces(
            addr,
            cfg.CONF.akanda_mgt_service_port
        )

        if not self._verify_interfaces(self.router_obj, interfaces):
            # FIXME: Need a REPLUG state when we support hot-plugging
            # interfaces.
            self.state = RESTART
            return

        # FIXME: Need to catch errors talking to neutron here.
        config = configuration.build_config(
            self.quantum,
            self.router_obj,
            interfaces
        )

        for i in xrange(cfg.CONF.max_retries):
            try:
                router_api.update_config(
                    addr,
                    cfg.CONF.akanda_mgt_service_port,
                    config
                )
            except Exception:
                if i == cfg.CONF.max_retries - 1:
                    # Only log the traceback if we encounter it many times.
                    self.log.exception('failed to update config')
                else:
                    self.log.debug('failed to update config')
                time.sleep(cfg.CONF.retry_delay)
            else:
                self.state = CONFIGURED
                self.log.info('Router config updated')
                return

    def _ensure_cache(self):
        if self.router_obj:
            return
        self.router_obj = self.quantum.get_router_detail(self.router_id)

    def _verify_interfaces(self, logical_config, interfaces):
        router_macs = set((iface['lladdr'] for iface in interfaces))
        self.log.debug('MACs found: %s', ', '.join(sorted(router_macs)))

        expected_macs = set(p.mac_address
                            for p in logical_config.internal_ports)
        expected_macs.add(logical_config.management_port.mac_address)
        expected_macs.add(logical_config.external_port.mac_address)
        self.log.debug('MACs expected: %s', ', '.join(sorted(expected_macs)))

        return router_macs == expected_macs

    def _ensure_provider_ports(self, router):
        if router.management_port is None:
            self.log.debug('Adding management port to router')
            mgt_port = self.quantum.create_router_management_port(router.id)
            router.management_port = mgt_port

        if router.external_port is None:
            # FIXME: Need to do some work to pick the right external
            # network for a tenant.
            self.log.debug('Adding external port to router')
            ext_port = self.quantum.create_router_external_port(router)
            router.external_port = ext_port
        return router


def _get_management_address(router):
    network = netaddr.IPNetwork(cfg.CONF.management_prefix)

    tokens = ['%02x' % int(t, 16)
              for t in router.management_port.mac_address.split(':')]
    eui64 = int(''.join(tokens[0:3] + ['ff', 'fe'] + tokens[3:6]), 16)

    # the bit inversion is required by the RFC
    return str(netaddr.IPAddress(network.value + (eui64 ^ 0x0200000000000000)))
