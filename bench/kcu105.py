#!/usr/bin/env python3

#
# This file is part of LiteSATA.
#
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import sys
import argparse

from migen import *

from litex_boards.platforms import kcu105

from litex.build.generic_platform import *

from litex.soc.cores.clock import USPLL
from litex.soc.interconnect.csr import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *

from litesata.common import *
from litesata.phy import LiteSATAPHY
from litesata.core import LiteSATACore
from litesata.frontend.arbitration import LiteSATACrossbar
from litesata.frontend.bist import LiteSATABIST

from litescope import LiteScopeAnalyzer

_sata_io = [
    # AB09-FMCRAID / https://www.dgway.com/AB09-FMCRAID_E.html
    ("fmc_refclk", 0, # 150MHz
        Subsignal("p", Pins("HPC:GBTCLK0_M2C_P")),
        Subsignal("n", Pins("HPC:GBTCLK0_M2C_N"))
    ),
    ("fmc", 0,
        Subsignal("tx_p", Pins("HPC:DP0_C2M_P")),
        Subsignal("tx_n", Pins("HPC:DP0_C2M_N")),
        Subsignal("rx_p", Pins("HPC:DP0_M2C_P")),
        Subsignal("rx_n", Pins("HPC:DP0_M2C_N"))
    ),
    ("pcie", 0,
        Subsignal("rx_p",  Pins("AB2")),
        Subsignal("rx_n",  Pins("AB1")),
        Subsignal("tx_p",  Pins("AC4")),
        Subsignal("tx_n",  Pins("AC3"))
    )
]


# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq):
        self.clock_domains.cd_sys = ClockDomain()

        # # #

        # PLL
        self.submodules.pll = pll = USPLL(speedgrade=-2)
        pll.register_clkin(platform.request("clk125"), 125e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)

# SATATestSoC --------------------------------------------------------------------------------------

class SATATestSoC(SoCMini):
    def __init__(self, platform, connector="fmc", gen="gen2", with_analyzer=False):
        assert connector in ["fmc", "sfp", "pcie"]
        assert gen in ["gen1", "gen2", "gen3"]

        sys_clk_freq  = int(187.50e6)
        sata_clk_freq = {"gen1": 75e6, "gen2": 150e6, "gen3": 300e6}[gen]

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq)

        # SoCMini ----------------------------------------------------------------------------------
        SoCMini.__init__(self, platform, sys_clk_freq,
            ident         = "LiteSATA bench on KCU105",
            ident_version = True,
            with_uart     = True,
            uart_name     = "bridge")

        # SATA -------------------------------------------------------------------------------------
        # RefClk
        if connector == "fmc_abc":
            # Use 150MHz refclk provided by FMC.
            sata_refclk = platform.request("fmc_refclk")
        else:
            # Generate 150MHz from PLL.
            # RefClk, Generate 150MHz from PLL.
            self.clock_domains.cd_sata_refclk = ClockDomain()
            self.crg.pll.create_clkout(self.cd_sata_refclk, 150e6, buf = None)
            sata_refclk = ClockSignal("sata_refclk")
            platform.add_platform_command("set_property SEVERITY {{Warning}} [get_drc_checks REQP-49]")

        # PHY
        self.submodules.sata_phy = LiteSATAPHY(platform.device,
            refclk     = sata_refclk,
            pads       = platform.request(connector),
            gen        = gen,
            clk_freq   = sys_clk_freq,
            data_width = 16)
        self.add_csr("sata_phy")

        # Core
        self.submodules.sata_core = LiteSATACore(self.sata_phy)

        # Crossbar
        self.submodules.sata_crossbar = LiteSATACrossbar(self.sata_core)

        # BIST
        self.submodules.sata_bist = LiteSATABIST(self.sata_crossbar, with_csr=True)
        self.add_csr("sata_bist")

        # Timing constraints
        platform.add_period_constraint(self.sata_phy.crg.cd_sata_tx.clk, 1e9/sata_clk_freq)
        platform.add_period_constraint(self.sata_phy.crg.cd_sata_rx.clk, 1e9/sata_clk_freq)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            self.sata_phy.crg.cd_sata_tx.clk,
            self.sata_phy.crg.cd_sata_rx.clk)

        # Leds -------------------------------------------------------------------------------------
        # sys_clk
        
        sys_counter = Signal(32)
        self.sync.sys += sys_counter.eq(sys_counter + 1)
        self.comb += platform.request("user_led", 0).eq(~sys_counter[26])
        # tx_clk
        tx_counter = Signal(32)
        self.sync.sata_tx += tx_counter.eq(tx_counter + 1)
        self.comb += platform.request("user_led", 1).eq(~tx_counter[26])
        # rx_clk
        rx_counter = Signal(32)
        self.sync.sata_rx += rx_counter.eq(rx_counter + 1)
        self.comb += platform.request("user_led", 2).eq(~rx_counter[26])
        # ready
        self.comb += platform.request("user_led", 3).eq(~self.sata_phy.ctrl.ready)
        
        # Analyzer ---------------------------------------------------------------------------------
        platform.add_source("clkcnt.v")
        if with_analyzer:
            analyzer_signals = [
                self.sata_phy.phy.tx_init.fsm,
                self.sata_phy.phy.rx_init.fsm,
                self.sata_phy.ctrl.fsm,
                #self.sata_phy.phy.tx_cominit_stb,
                #self.sata_phy.phy.txcominit_db,
                #self.sata_phy.phy.txcomfinish_db,
                self.sata_phy.phy.txcomwake_db,
                #self.sata_phy.phy.rxcominit_db,
                self.sata_phy.phy.rxcomwake_db,
                self.sata_phy.phy.txclk_period,
                self.sata_phy.phy.rxclk_period,
                self.sata_phy.ctrl.misalign,
                self.sata_phy.ctrl.rx_idle,
            ]

            self.submodules.analyzer = LiteScopeAnalyzer(analyzer_signals, 512, csr_csv="analyzer.csv")
            self.add_csr("analyzer")

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteSATA bench on KCU105")
    parser.add_argument("--build",         action="store_true", help="Build bitstream")
    parser.add_argument("--load",          action="store_true", help="Load bitstream (to SRAM)")
    parser.add_argument("--gen",           default="2",         help="SATA Gen: 1 or 2 (default) or 3")
    parser.add_argument("--connector",     default="fmc",       help="SATA Connector: fmc (default) , sfp or pcie")
    parser.add_argument("--with-analyzer", action="store_true", help="Add LiteScope Analyzer")
    args = parser.parse_args()

    platform = kcu105.Platform()
    platform.add_extension(_sata_io)
    soc = SATATestSoC(platform, args.connector, "gen" + args.gen, with_analyzer=args.with_analyzer)
    builder = Builder(soc, csr_csv="csr.csv")
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".bit"))

if __name__ == "__main__":
    main()
