#!/usr/bin/env python3
# encoding: utf-8
#
# Purpose: build a small transit-AS topology that uses iBGP route reflectors.
# Inputs: optional platform argument, either "amd" or "arm".
# Outputs: Docker Compose files under ./output when run directly.
# Side effects: render/compile writes ./output; deployment is done separately with
# docker compose build/up from that directory.
# Context: run from this directory in the seedpy310 conda environment.

from seedemu import *
import os
import sys


WEST_CLUSTER_ID = "10.62.0.1"
EAST_CLUSTER_ID = "10.62.0.2"


def enableBgpOnRouters(*nodes):
    """Enable BIRD protocols after the routing daemon starts."""
    for node in nodes:
        node.appendStartCommand('sh -c "sleep 5; birdc enable all || true"', fork = True, isPostConfigCommand = True)


def run(dumpfile = None):
    if dumpfile is None:
        script_name = os.path.basename(__file__)

        if len(sys.argv) == 1:
            platform = Platform.AMD64
        elif len(sys.argv) == 2:
            if sys.argv[1].lower() == 'amd':
                platform = Platform.AMD64
            elif sys.argv[1].lower() == 'arm':
                platform = Platform.ARM64
            else:
                print(f"Usage:  {script_name} amd|arm")
                sys.exit(1)
        else:
            print(f"Usage:  {script_name} amd|arm")
            sys.exit(1)

    emu  = Emulator()
    base = Base()
    ebgp = Ebgp()
    web  = WebService()

    ###############################################################################
    # Create Internet exchanges used by the transit AS and the two stub ASes.

    ix100 = base.createInternetExchange(100)
    ix101 = base.createInternetExchange(101)

    ###############################################################################
    # Create AS62. It uses two iBGP route-reflector clusters.

    as62 = base.createAutonomousSystem(62)

    as62.createNetwork('net_w_edge')
    as62.createNetwork('net_w_core')
    as62.createNetwork('net_rr')
    as62.createNetwork('net_e_core')
    as62.createNetwork('net_e_edge')

    # Register cluster IDs before routers join them. The ID is rendered as
    # BIRD's rr cluster id, so an IPv4-looking value is used here.
    as62.createCluster(WEST_CLUSTER_ID)
    as62.createCluster(EAST_CLUSTER_ID)

    # West cluster: edge100 and core_west are clients; rr_west is the RR.
    as62.createRouter('edge100') \
        .joinNetwork('ix100') \
        .joinNetwork('net_w_edge') \
        .joinBgpCluster(WEST_CLUSTER_ID)

    as62.createRouter('core_west') \
        .joinNetwork('net_w_core') \
        .joinBgpCluster(WEST_CLUSTER_ID)

    as62.createRouter('rr_west') \
        .joinNetwork('net_w_edge') \
        .joinNetwork('net_w_core') \
        .joinNetwork('net_rr') \
        .joinBgpCluster(WEST_CLUSTER_ID) \
        .makeRouteReflector()

    # East cluster: edge101 and core_east are clients; rr_east is the RR.
    as62.createRouter('rr_east') \
        .joinNetwork('net_rr') \
        .joinNetwork('net_e_core') \
        .joinNetwork('net_e_edge') \
        .joinBgpCluster(EAST_CLUSTER_ID) \
        .makeRouteReflector()

    as62.createRouter('core_east') \
        .joinNetwork('net_e_core') \
        .joinBgpCluster(EAST_CLUSTER_ID)

    as62.createRouter('edge101') \
        .joinNetwork('ix101') \
        .joinNetwork('net_e_edge') \
        .joinBgpCluster(EAST_CLUSTER_ID)

    ###############################################################################
    # Create two stub ASes. Their prefixes should be carried across AS62.

    as150 = base.createAutonomousSystem(150)
    as150.createNetwork('net0')
    as150.createRouter('router0').joinNetwork('net0').joinNetwork('ix100')
    as150.createHost('web').joinNetwork('net0')
    web.install('web150')
    emu.addBinding(Binding('web150', filter = Filter(nodeName = 'web', asn = 150)))

    as151 = base.createAutonomousSystem(151)
    as151.createNetwork('net0')
    as151.createRouter('router0').joinNetwork('net0').joinNetwork('ix101')
    as151.createHost('web').joinNetwork('net0')
    web.install('web151')
    emu.addBinding(Binding('web151', filter = Filter(nodeName = 'web', asn = 151)))

    enableBgpOnRouters(
        ix100.getRouteServerNode(),
        ix101.getRouteServerNode(),
        *[as62.getRouter(name) for name in as62.getRouters()],
        *[as150.getRouter(name) for name in as150.getRouters()],
        *[as151.getRouter(name) for name in as151.getRouters()],
    )

    ###############################################################################
    # AS62 is the provider for both stub ASes.

    ebgp.addPrivatePeering(100, 62, 150, abRelationship = PeerRelationship.Provider)
    ebgp.addPrivatePeering(101, 62, 151, abRelationship = PeerRelationship.Provider)

    ###############################################################################
    # Add layers. Ibgp will detect RR metadata and use RR mode for AS62, while
    # AS150 and AS151 still use the normal single-router/full-mesh path.

    emu.addLayer(base)
    emu.addLayer(Routing())
    emu.addLayer(ebgp)
    emu.addLayer(Ibgp())
    emu.addLayer(Ospf())
    emu.addLayer(web)

    if dumpfile is not None:
        emu.dump(dumpfile)
    else:
        emu.render()
        emu.compile(Docker(platform = platform), './output', override = True)


if __name__ == "__main__":
    run()
