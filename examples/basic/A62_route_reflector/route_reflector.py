#!/usr/bin/env python3
# encoding: utf-8
#
# Purpose: build a mini-Internet topology that demonstrates three iBGP modes:
# legacy full mesh, one Route Reflector in an AS, and two Route Reflectors in an
# AS. The topology follows examples/internet/B00_mini_internet/mini_internet.py.
# Inputs: optional platform argument, either "amd" or "arm".
# Outputs: Docker Compose files under ./output when run directly.
# Side effects: render/compile writes ./output; deployment is done separately
# with docker compose build/up from that directory.
# Context: run from this directory in the seedpy310 conda environment.

from seedemu.layers import Base, Routing, Ebgp, Ibgp, Ospf, PeerRelationship
from seedemu.compiler import Docker, Platform
from seedemu.core import Emulator, OptionMode, OptionRegistry
from seedemu.utilities import Makers
import os
import sys


AS12_CLUSTER_ID = "10.12.0.1"
AS3_WEST_CLUSTER_ID = "10.3.0.1"
AS3_EAST_CLUSTER_ID = "10.3.0.2"


def parsePlatform() -> Platform:
    """Return the Docker platform selected by the optional CLI argument."""
    script_name = os.path.basename(__file__)

    if len(sys.argv) == 1:
        return Platform.AMD64
    if len(sys.argv) == 2:
        if sys.argv[1].lower() == 'amd':
            return Platform.AMD64
        if sys.argv[1].lower() == 'arm':
            return Platform.ARM64

    print(f"Usage:  {script_name} amd|arm")
    sys.exit(1)


def buildMiniInternet(emu: Emulator, base: Base, ebgp: Ebgp, hosts_per_as: int):
    """Create the B00 mini-Internet topology and add selected RR metadata.

    @param emu emulator that receives stub host bindings.
    @param base Base layer where ASes, IXes, routers, networks, and hosts are
    created.
    @param ebgp Ebgp layer where inter-AS peering relationships are added.
    @param hosts_per_as number of hosts to create in each stub AS.
    """
    ix100 = base.createInternetExchange(100)
    ix101 = base.createInternetExchange(101)
    ix102 = base.createInternetExchange(102)
    ix103 = base.createInternetExchange(103)
    ix104 = base.createInternetExchange(104)
    ix105 = base.createInternetExchange(105)

    ix100.getPeeringLan().setDisplayName('NYC-100')
    ix101.getPeeringLan().setDisplayName('San Jose-101')
    ix102.getPeeringLan().setDisplayName('Chicago-102')
    ix103.getPeeringLan().setDisplayName('Miami-103')
    ix104.getPeeringLan().setDisplayName('Boston-104')
    ix105.getPeeringLan().setDisplayName('Houston-105')

    Makers.makeTransitAs(
        base, 2, [100, 101, 102, 105],
        [(100, 101), (101, 102), (100, 105)]
    )
    Makers.makeTransitAs(
        base, 3, [100, 103, 104, 105],
        [(100, 103), (100, 105), (103, 105), (103, 104)]
    )
    Makers.makeTransitAs(
        base, 4, [100, 102, 104],
        [(100, 104), (102, 104)]
    )

    Makers.makeTransitAs(base, 11, [102, 105], [(102, 105)])
    Makers.makeTransitAs(base, 12, [101, 104], [(101, 104)])

    # AS2 keeps the B00 behavior and is rendered by Ibgp as legacy full mesh.

    # AS12 demonstrates one RR and one client in a single cluster.
    as12 = base.getAutonomousSystem(12)
    as12.createCluster(AS12_CLUSTER_ID)
    as12.getRouter('r101') \
        .joinBgpCluster(AS12_CLUSTER_ID) \
        .makeRouteReflector()
    as12.getRouter('r104') \
        .joinBgpCluster(AS12_CLUSTER_ID)

    # AS3 demonstrates two RR clusters and an RR mesh between the RRs.
    as3 = base.getAutonomousSystem(3)
    as3.createCluster(AS3_WEST_CLUSTER_ID)
    as3.createCluster(AS3_EAST_CLUSTER_ID)
    as3.getRouter('r100') \
        .joinBgpCluster(AS3_WEST_CLUSTER_ID) \
        .makeRouteReflector()
    as3.getRouter('r105') \
        .joinBgpCluster(AS3_WEST_CLUSTER_ID)
    as3.getRouter('r103') \
        .joinBgpCluster(AS3_EAST_CLUSTER_ID) \
        .makeRouteReflector()
    as3.getRouter('r104') \
        .joinBgpCluster(AS3_EAST_CLUSTER_ID)

    Makers.makeStubAsWithHosts(emu, base, 150, 100, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 151, 100, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 152, 101, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 153, 101, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 154, 102, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 160, 103, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 161, 103, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 162, 103, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 163, 104, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 164, 104, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 170, 105, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 171, 105, hosts_per_as)

    ebgp.addRsPeers(100, [2, 3, 4])
    ebgp.addRsPeers(102, [2, 4])
    ebgp.addRsPeers(104, [3, 4])
    ebgp.addRsPeers(105, [2, 3])

    ebgp.addPrivatePeerings(100, [2],  [150, 151], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(100, [3],  [150], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(101, [2],  [12], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(101, [12], [152, 153], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(102, [2, 4], [11, 154], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(102, [11], [154], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(103, [3], [160, 161, 162], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(104, [3, 4], [12], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(104, [4], [163], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(104, [12], [164], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(105, [3], [11, 170], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(105, [11], [171], PeerRelationship.Provider)


def run(dumpfile = None, hosts_per_as = 2):
    """Render or dump the mini-Internet RR example.

    @param dumpfile optional component output file. When set, the emulator is
    dumped before render/compile.
    @param hosts_per_as number of hosts to create in each stub AS.
    """
    if dumpfile is None:
        platform = parsePlatform()

    emu = Emulator()
    base = Base()
    ebgp = Ebgp()

    buildMiniInternet(emu, base, ebgp, hosts_per_as)

    emu.addLayer(base)
    emu.addLayer(Routing())
    emu.addLayer(ebgp)
    emu.addLayer(Ibgp())
    emu.addLayer(Ospf())

    if dumpfile is not None:
        emu.dump(dumpfile)
    else:
        emu.render()
        emu.compile(Docker(platform = platform), './output', override = True)


if __name__ == "__main__":
    run()
