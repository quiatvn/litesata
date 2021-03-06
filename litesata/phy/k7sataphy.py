#
# This file is part of LiteSATA.
#
# Copyright (c) 2015-2020 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2017 Johan Klockars <Johan.Klockars@hasselblad.com>
# Copyright (c) 2015-2016 Olof Kindgren <olof.kindgren@gmail.com>
# SPDX-License-Identifier: BSD-2-Clause

from litesata.common import *
from litesata.common import _PulseSynchronizer, _RisingEdge

from migen.genlib.cdc import MultiReg
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex.soc.cores.clock import S7MMCM

from liteiclink.serdes.gtx_7series_init import GTXTXInit, GTXRXInit

# --------------------------------------------------------------------------------------------------

class K7LiteSATAPHYCRG(Module):
    def __init__(self, refclk, pads, gtx, gen):
        self.tx_reset = Signal()
        self.rx_reset = Signal()

        self.clock_domains.cd_sata_tx = ClockDomain()
        self.clock_domains.cd_sata_rx = ClockDomain()

        # CPLL -------------------------------------------------------------------------------------
        #   (gen3) 150MHz / VCO @ 3GHz / Linerate @ 6Gbps
        #   (gen2 & gen1) VCO still @ 3 GHz, Linerate is decreased with output dividers.
        if isinstance(refclk, (Signal, ClockSignal)):
            self.refclk = refclk
        else:
            self.refclk = Signal()
            clock_pads = refclk
            self.specials += Instance("IBUFDS_GTE2",
                i_CEB = 0,
                i_I   = refclk.p,
                i_IB  = refclk.n,
                o_O   = self.refclk
            )
        self.comb += gtx.gtrefclk0.eq(self.refclk)

        # TX clocking ------------------------------------------------------------------------------
        #   (gen3) 150MHz from CPLL TXOUTCLK, sata_tx clk @ 300MHz (16-bits) /  150MHz (32-bits)
        #   (gen2) 150MHz from CPLL TXOUTCLK, sata_tx clk @ 150MHz (16-bits) /   75MHz (32-bits)
        #   (gen1) 150MHz from CPLL TXOUTCLK, sata_tx clk @ 75MHz  (16-bits) / 37.5MHz (32-bits)
        tx_mmcm_clkin = Signal()
        tx_mmcm = S7MMCM(speedgrade=-1)
        tx_mmcm_clkout_freq = {
            "gen1":  75e6/(gtx.data_width/16),
            "gen2": 150e6/(gtx.data_width/16),
            "gen3": 300e6/(gtx.data_width/16),
        }
        self.submodules += tx_mmcm
        self.specials += Instance("BUFG", i_I=gtx.txoutclk, o_O=tx_mmcm_clkin)
        tx_mmcm.register_clkin(tx_mmcm_clkin, 150e6)
        tx_mmcm.create_clkout(self.cd_sata_tx, tx_mmcm_clkout_freq[gen], with_reset=False)

        self.comb += gtx.txusrclk.eq(self.cd_sata_tx.clk)
        self.comb += gtx.txusrclk2.eq(self.cd_sata_tx.clk)

        # RX clocking ------------------------------------------------------------------------------
        #   (gen3) sata_rx recovered clk @ 300MHz (16-bits) /  150MHz (32-bits) from GTX RXOUTCLK
        #   (gen2) sata_rx recovered clk @ 150MHz (16-bits) /   75MHz (32-bits) from GTX RXOUTCLK
        #   (gen1) sata_rx recovered clk @ 75MHz  (16-bits) / 37.5MHz (32-bits) from GTX RXOUTCLK
        self.specials += Instance("BUFG", i_I=gtx.rxoutclk, o_O=self.cd_sata_rx.clk)

        self.comb += gtx.rxusrclk.eq(self.cd_sata_rx.clk)
        self.comb += gtx.rxusrclk2.eq(self.cd_sata_rx.clk)

        # Reset for SATA TX/RX clock domains -------------------------------------------------------
        self.specials += [
            AsyncResetSynchronizer(self.cd_sata_tx, ~(gtx.cplllock & tx_mmcm.locked) | self.tx_reset),
            AsyncResetSynchronizer(self.cd_sata_rx, ~gtx.cplllock | self.rx_reset)
        ]

# --------------------------------------------------------------------------------------------------

class K7LiteSATAPHY(Module):
    def __init__(self, pads, gen, clk_freq, data_width=16):
        assert data_width in [16, 32]
        # Common signals
        self.data_width     = data_width

        # Control
        self.ready          = Signal() # o

        self.tx_idle        = Signal()  # i

        self.tx_cominit_stb = Signal()  # i
        self.tx_cominit_ack = Signal()  # o
        self.tx_comwake_stb = Signal()  # i
        self.tx_comwake_ack = Signal()  # o

        self.rx_idle        = Signal()  # o
        self.rx_cdrhold     = Signal()  # i

        self.rx_cominit_stb = Signal()  # o
        self.rx_comwake_stb = Signal()  # o

        self.rxdisperr      = Signal(data_width//8) # o
        self.rxnotintable   = Signal(data_width//8) # o

        # Datapath
        self.sink           = stream.Endpoint(phy_description(data_width))
        self.source         = stream.Endpoint(phy_description(data_width))

        # K7 specific signals
        # Channel - Ref Clock Ports
        self.gtrefclk0      = Signal()

        # Channel PLL
        self.cplllock       = Signal()

        # Receive Ports - 8b10b Decoder
        self.rxcharisk      = Signal(data_width//8)

        # Receive Ports - RX Data Path interface
        self.rxdata         = Signal(data_width)
        self.rxoutclk       = Signal()
        self.rxusrclk       = Signal()
        self.rxusrclk2      = Signal()

        # Receive Ports - RX Ports for SATA
        self.rxcominitdet   = Signal()
        self.rxcomwakedet   = Signal()

        # Transmit Ports - 8b10b Encoder Control Ports
        self.txcharisk      = Signal(data_width//8)

        # Transmit Ports - TX Data Path interface
        self.txdata         = Signal(data_width)
        self.txoutclk       = Signal()
        self.txusrclk       = Signal()
        self.txusrclk2      = Signal()

        # Transmit Ports - TX Ports for PCI Express
        self.txelecidle     = Signal(reset=1)

        # Transmit Ports - TX Ports for SATA
        self.txcomfinish    = Signal()
        self.txcominit      = Signal()
        self.txcomwake      = Signal()

        # Power-down signals
        self.cpllpd         = Signal()
        self.rxpd           = Signal()
        self.txpd           = Signal()

        # Config at startup
        div_config = {
            "gen1": 4,
            "gen2": 2,
            "gen3": 1,
        }
        rxout_div = div_config[gen]
        txout_div = div_config[gen]

        cdr_config = {
            "gen1": 0x0380008bff40100008,
            "gen2": 0x0388008bff40200008,
            "gen3": 0x0380008bff10200010,
        }
        rxcdr_cfg = cdr_config[gen]

        # TX Init ----------------------------------------------------------------------------------
        self.submodules.tx_init = tx_init = GTXTXInit(clk_freq, buffer_enable=False)
        self.comb += tx_init.plllock.eq(self.cplllock)

        # RX Init ----------------------------------------------------------------------------------
        self.submodules.rx_init = rx_init = GTXRXInit(clk_freq, buffer_enable=False)
        self.comb += rx_init.plllock.eq(self.cplllock)

        # Ready ------------------------------------------------------------------------------------
        self.comb += self.ready.eq(tx_init.done & rx_init.done)

        # Specific / Generic signals encoding/decoding ---------------------------------------------
        self.comb += [
            self.txelecidle.eq(self.tx_idle | self.txpd),
            self.tx_cominit_ack.eq(self.tx_cominit_stb & self.txcomfinish),
            self.tx_comwake_ack.eq(self.tx_comwake_stb & self.txcomfinish),
            self.rx_cominit_stb.eq(self.rxcominitdet),
            self.rx_comwake_stb.eq(self.rxcomwakedet),
        ]
        self.submodules += _RisingEdge(self.tx_cominit_stb, self.txcominit)
        self.submodules += _RisingEdge(self.tx_comwake_stb, self.txcomwake)

        self.sync.sata_rx += [
            self.source.valid.eq(1),
            self.source.charisk.eq(self.rxcharisk),
            self.source.data.eq(self.rxdata)
        ]

        self.sync.sata_tx += [
            self.txcharisk.eq(self.sink.charisk),
            self.txdata.eq(self.sink.data),
            self.sink.ready.eq(1),
        ]

        # Internals and clock domain crossing ------------------------------------------------------
        # sys_clk --> sata_tx clk
        txpd       = Signal()
        txelecidle = Signal(reset=1)
        txcominit  = Signal()
        txcomwake  = Signal()
        self.specials += [
            MultiReg(self.txpd,             txpd, "sata_tx"),
            MultiReg(self.txelecidle, txelecidle, "sata_tx"),
        ]
        self.submodules += [
            _PulseSynchronizer(self.txcominit,  "sys",  txcominit, "sata_tx"),
            _PulseSynchronizer(self.txcomwake,  "sys",  txcomwake, "sata_tx"),
        ]

        # sata_tx clk --> sys clk
        txcomfinish = Signal()
        self.submodules += _PulseSynchronizer(txcomfinish, "sata_tx", self.txcomfinish, "sys")

        # sata_rx clk --> sys clk
        rxcominitdet = Signal()
        rxcomwakedet = Signal()
        rxratedone   = Signal()
        rxdisperr    = Signal(data_width//8)
        rxnotintable = Signal(data_width//8)
        self.specials += [
            MultiReg(rxcominitdet, self.rxcominitdet, "sys"),
            MultiReg(rxcomwakedet, self.rxcomwakedet, "sys"),
            MultiReg(rxdisperr, self.rxdisperr, "sys"),
            MultiReg(rxnotintable, self.rxnotintable, "sys")
        ]

        # QPLL input clock -------------------------------------------------------------------------
        self.qpllclk    = Signal()
        self.qpllrefclk = Signal()

        # OOB clock (75MHz) ------------------------------------------------------------------------
        oobclk = Signal()
        self.specials += Instance("FDPE",
            p_INIT = 1,
            i_CE   = 1,
            i_PRE  = 0,
            i_C    = self.gtrefclk0,
            i_D    = ~oobclk,
            o_Q    = oobclk
        )

        # GTXE2_CHANNEL Instance -------------------------------------------------------------------
        class Open(Signal): pass
        tx_buffer_enable = False
        rx_buffer_enable = False
        gtx_params = dict(
            # Simulation-Only Attributes
            p_SIM_RECEIVER_DETECT_PASS     = "TRUE",
            p_SIM_TX_EIDLE_DRIVE_LEVEL     = "X",
            p_SIM_RESET_SPEEDUP            = "FALSE",
            p_SIM_CPLLREFCLK_SEL           = "FALSE",
            p_SIM_VERSION                  = "4.0",

            # RX Byte and Word Alignment Attributes
            p_ALIGN_COMMA_DOUBLE           = "FALSE",
            p_ALIGN_COMMA_ENABLE           = 0b1111111111,
            p_ALIGN_COMMA_WORD             = 2 if data_width == 16 else 4,
            p_ALIGN_MCOMMA_DET             = "TRUE",
            p_ALIGN_MCOMMA_VALUE           = 0b1010000011,
            p_ALIGN_PCOMMA_DET             = "TRUE",
            p_ALIGN_PCOMMA_VALUE           = 0b0101111100,
            p_SHOW_REALIGN_COMMA           = "TRUE",
            p_RXSLIDE_AUTO_WAIT            = 7,
            p_RXSLIDE_MODE                 = "OFF" if rx_buffer_enable else "PCS",
            p_RX_SIG_VALID_DLY             = 10,

            # RX 8B/10B Decoder Attributes
            p_RX_DISPERR_SEQ_MATCH         = "TRUE",
            p_DEC_MCOMMA_DETECT            = "TRUE",
            p_DEC_PCOMMA_DETECT            = "TRUE",
            p_DEC_VALID_COMMA_ONLY         = "TRUE",

            # RX Clock Correction Attributes
            p_CBCC_DATA_SOURCE_SEL         = "DECODED",
            p_CLK_COR_SEQ_2_USE            = "FALSE",
            p_CLK_COR_KEEP_IDLE            = "FALSE",
            p_CLK_COR_MAX_LAT              = 9 if data_width == 16 else 20,
            p_CLK_COR_MIN_LAT              = 7 if data_width == 16 else 16,
            p_CLK_COR_PRECEDENCE           = "TRUE",
            p_CLK_COR_REPEAT_WAIT          = 0,
            p_CLK_COR_SEQ_LEN              = 1,
            p_CLK_COR_SEQ_1_ENABLE         = 0b1111,
            p_CLK_COR_SEQ_1_1              = 0b0100000000,
            p_CLK_COR_SEQ_1_2              = 0b0000000000,
            p_CLK_COR_SEQ_1_3              = 0b0000000000,
            p_CLK_COR_SEQ_1_4              = 0b0000000000,
            p_CLK_CORRECT_USE              = "FALSE",
            p_CLK_COR_SEQ_2_ENABLE         = 0b1111,
            p_CLK_COR_SEQ_2_1              = 0b0100000000,
            p_CLK_COR_SEQ_2_2              = 0b0000000000,
            p_CLK_COR_SEQ_2_3              = 0b0000000000,
            p_CLK_COR_SEQ_2_4              = 0b0000000000,

            # RX Channel Bonding Attributes
            p_CHAN_BOND_KEEP_ALIGN         = "FALSE",
            p_CHAN_BOND_MAX_SKEW           = 1,
            p_CHAN_BOND_SEQ_LEN            = 1,
            p_CHAN_BOND_SEQ_1_1            = 0b0000000000,
            p_CHAN_BOND_SEQ_1_2            = 0b0000000000,
            p_CHAN_BOND_SEQ_1_3            = 0b0000000000,
            p_CHAN_BOND_SEQ_1_4            = 0b0000000000,
            p_CHAN_BOND_SEQ_1_ENABLE       = 0b1111,
            p_CHAN_BOND_SEQ_2_1            = 0b0000000000,
            p_CHAN_BOND_SEQ_2_2            = 0b0000000000,
            p_CHAN_BOND_SEQ_2_3            = 0b0000000000,
            p_CHAN_BOND_SEQ_2_4            = 0b0000000000,
            p_CHAN_BOND_SEQ_2_ENABLE       = 0b1111,
            p_CHAN_BOND_SEQ_2_USE          = "FALSE",
            p_FTS_DESKEW_SEQ_ENABLE        = 0b1111,
            p_FTS_LANE_DESKEW_CFG          = 0b1111,
            p_FTS_LANE_DESKEW_EN           = "FALSE",

            # RX Margin Analysis Attributes
            p_ES_CONTROL                   = 0b000000,
            p_ES_ERRDET_EN                 = "FALSE",
            p_ES_EYE_SCAN_EN               = "TRUE",
            p_ES_HORZ_OFFSET               = 0x000,
            p_ES_PMA_CFG                   = 0b0000000000,
            p_ES_PRESCALE                  = 0b00000,
            p_ES_QUALIFIER                 = 0x00000000000000000000,
            p_ES_QUAL_MASK                 = 0x00000000000000000000,
            p_ES_SDATA_MASK                = 0x00000000000000000000,
            p_ES_VERT_OFFSET               = 0b000000000,

            # FPGA RX Interface Attributes
            p_RX_DATA_WIDTH                = 20 if data_width == 16 else 40,

            # PMA Attributes
            p_OUTREFCLK_SEL_INV            = 0b11,
            p_PMA_RSV                      = 0x00018480,
            p_PMA_RSV2                     = 0x2050,
            p_PMA_RSV3                     = 0b00,
            p_PMA_RSV4                     = 0x00000000,
            p_RX_BIAS_CFG                  = 0b000000000100,
            p_DMONITOR_CFG                 = 0x000A00,
            p_RX_CM_SEL                    = 0b11,
            p_RX_CM_TRIM                   = 0b010,
            p_RX_DEBUG_CFG                 = 0b000000000000,
            p_RX_OS_CFG                    = 0b0000010000000,
            p_TERM_RCAL_CFG                = 0b10000,
            p_TERM_RCAL_OVRD               = 0b0,
            p_TST_RSV                      = 0x00000000,
            p_RX_CLK25_DIV                 = 6,
            p_TX_CLK25_DIV                 = 6,
            p_UCODEER_CLR                  = 0b0,

            # PCI Express Attributes
            p_PCS_PCIE_EN                  = "FALSE",

            # PCS Attributes
            p_PCS_RSVD_ATTR                = 0x108 if gen == "gen1" else 0x100,

            # RX Buffer Attributes
            p_RXBUF_ADDR_MODE              = "FAST",
            p_RXBUF_EIDLE_HI_CNT           = 0b1000,
            p_RXBUF_EIDLE_LO_CNT           = 0b0000,
            p_RXBUF_EN                     = "TRUE" if rx_buffer_enable else "FALSE",
            p_RX_BUFFER_CFG                = 0b000000,
            p_RXBUF_RESET_ON_CB_CHANGE     = "TRUE",
            p_RXBUF_RESET_ON_COMMAALIGN    = "FALSE",
            p_RXBUF_RESET_ON_EIDLE         = "FALSE",
            p_RXBUF_RESET_ON_RATE_CHANGE   = "TRUE",
            p_RXBUFRESET_TIME              = 0b00001,
            p_RXBUF_THRESH_OVFLW           = 61,
            p_RXBUF_THRESH_OVRD            = "FALSE",
            p_RXBUF_THRESH_UNDFLW          = 4,
            p_RXDLY_CFG                    = 0x001F,
            p_RXDLY_LCFG                   = 0x030,
            p_RXDLY_TAP_CFG                = 0x0000,
            p_RXPH_CFG                     = 0x000000,
            p_RXPHDLY_CFG                  = 0x084020,
            p_RXPH_MONITOR_SEL             = 0b00000,
            p_RX_XCLK_SEL                  = "RXREC" if rx_buffer_enable else "RXUSR",
            p_RX_DDI_SEL                   = 0b000000,
            p_RX_DEFER_RESET_BUF_EN        = "TRUE",

            # CDR Attributes
            p_RXCDR_CFG                    = rxcdr_cfg,
            p_RXCDR_FR_RESET_ON_EIDLE      = 0b0,
            p_RXCDR_HOLD_DURING_EIDLE      = 0b0,
            p_RXCDR_PH_RESET_ON_EIDLE      = 0b0,
            p_RXCDR_LOCK_CFG               = 0b010101,

            # RX Initialization and Reset Attributes
            p_RXCDRFREQRESET_TIME          = 0b00001,
            p_RXCDRPHRESET_TIME            = 0b00001,
            p_RXISCANRESET_TIME            = 0b00001,
            p_RXPCSRESET_TIME              = 0b00001,
            p_RXPMARESET_TIME              = 0b00011,

            # RX OOB Signaling Attributes
            p_RXOOB_CFG                    = 0b0000110,

            # RX Gearbox Attributes
            p_RXGEARBOX_EN                 = "FALSE",
            p_GEARBOX_MODE                 = 0b000,

            # PRBS Detection Attribute
            p_RXPRBS_ERR_LOOPBACK          = 0b0,

            # Power-Down Attributes
            p_PD_TRANS_TIME_FROM_P2        = 0x03c,
            p_PD_TRANS_TIME_NONE_P2        = 0x3c,
            p_PD_TRANS_TIME_TO_P2          = 0x64,

            # RX OOB Signaling Attributes
            p_SAS_MAX_COM                  = 64,
            p_SAS_MIN_COM                  = 36,
            p_SATA_BURST_SEQ_LEN           = 0b0101,
            p_SATA_BURST_VAL               = 0b100,
            p_SATA_EIDLE_VAL               = 0b100,
            p_SATA_MAX_BURST               = 8,
            p_SATA_MAX_INIT                = 21,
            p_SATA_MAX_WAKE                = 7,
            p_SATA_MIN_BURST               = 4,
            p_SATA_MIN_INIT                = 12,
            p_SATA_MIN_WAKE                = 4,

            # RX Fabric Clock Output Control Attributes
            p_TRANS_TIME_RATE              = 0x0E,

            # TX Buffer Attributes
            p_TXBUF_EN                     = "TRUE" if tx_buffer_enable else "FALSE",
            p_TXBUF_RESET_ON_RATE_CHANGE   = "TRUE",
            p_TXDLY_CFG                    = 0x001F,
            p_TXDLY_LCFG                   = 0x030,
            p_TXDLY_TAP_CFG                = 0x0000,
            p_TXPH_CFG                     = 0x0780,
            p_TXPHDLY_CFG                  = 0x084020,
            p_TXPH_MONITOR_SEL             = 0b00000,
            p_TX_XCLK_SEL                  = "TXOUT" if tx_buffer_enable else "TXUSR",

            # FPGA TX Interface Attributes
            p_TX_DATA_WIDTH                = 20 if data_width == 16 else 40,

            # TX Configurable Driver Attributes
            p_TX_DEEMPH0                   = 0b00000,
            p_TX_DEEMPH1                   = 0b00000,
            p_TX_EIDLE_ASSERT_DELAY        = 0b110,
            p_TX_EIDLE_DEASSERT_DELAY      = 0b100,
            p_TX_LOOPBACK_DRIVE_HIZ        = "FALSE",
            p_TX_MAINCURSOR_SEL            = 0b0,
            p_TX_DRIVE_MODE                = "DIRECT",
            p_TX_MARGIN_FULL_0             = 0b1001110,
            p_TX_MARGIN_FULL_1             = 0b1001001,
            p_TX_MARGIN_FULL_2             = 0b1000101,
            p_TX_MARGIN_FULL_3             = 0b1000010,
            p_TX_MARGIN_FULL_4             = 0b1000000,
            p_TX_MARGIN_LOW_0              = 0b1000110,
            p_TX_MARGIN_LOW_1              = 0b1000100,
            p_TX_MARGIN_LOW_2              = 0b1000010,
            p_TX_MARGIN_LOW_3              = 0b1000000,
            p_TX_MARGIN_LOW_4              = 0b1000000,

            # TX Gearbox Attributes
            p_TXGEARBOX_EN                 = "FALSE",

            # TX Initialization and Reset Attributes
            p_TXPCSRESET_TIME              = 0b00001,
            p_TXPMARESET_TIME              = 0b00001,

            # TX Receiver Detection Attributes
            p_TX_RXDETECT_CFG              = 0x1832,
            p_TX_RXDETECT_REF              = 0b100,

            # CPLL Attributes
            p_CPLL_CFG                     = 0xBC07DC,
            p_CPLL_FBDIV                   = 4,
            p_CPLL_FBDIV_45                = 5,
            p_CPLL_INIT_CFG                = 0x00001E,
            p_CPLL_LOCK_CFG                = 0x01E8,
            p_CPLL_REFCLK_DIV              = 1,
            p_RXOUT_DIV                    = rxout_div,
            p_TXOUT_DIV                    = txout_div,
            p_SATA_CPLL_CFG                = "VCO_3000MHZ",

            # RX Initialization and Reset Attributes
            p_RXDFELPMRESET_TIME           = 0b0001111,

            # RX Equalizer Attributes
            p_RXLPM_HF_CFG                 = 0b00000011110000,
            p_RXLPM_LF_CFG                 = 0b00000011110000,
            p_RX_DFE_GAIN_CFG              = 0x020FEA,
            p_RX_DFE_H2_CFG                = 0b000000000000,
            p_RX_DFE_H3_CFG                = 0b000001000000,
            p_RX_DFE_H4_CFG                = 0b00011110000,
            p_RX_DFE_H5_CFG                = 0b00011100000,
            p_RX_DFE_KL_CFG                = 0b0000011111110,
            p_RX_DFE_LPM_CFG               = 0x0954,
            p_RX_DFE_LPM_HOLD_DURING_EIDLE = 0b1,
            p_RX_DFE_UT_CFG                = 0b10001111000000000,
            p_RX_DFE_VP_CFG                = 0b00011111100000011,

            # Power-Down Attributes
            p_RX_CLKMUX_PD                 = 0b1,
            p_TX_CLKMUX_PD                 = 0b1,

            # FPGA RX Interface Attribute
            p_RX_INT_DATAWIDTH             = data_width == 32,

            # FPGA TX Interface Attribute
            p_TX_INT_DATAWIDTH             = data_width == 32,

            # TX Configurable Driver Attributes
            p_TX_QPI_STATUS_EN             = 0b0,

            # RX Equalizer Attributes
            p_RX_DFE_KL_CFG2               = 0x3310180c,
            p_RX_DFE_XYD_CFG               = 0b0000000000000,

            # TX Configurable Driver Attributes
            p_TX_PREDRIVER_MODE            = 0b0
        )
        gtx_params.update(
            # CPLL Ports
            o_CPLLFBCLKLOST    = Open(),
            o_CPLLLOCK         = self.cplllock,
            i_CPLLLOCKDETCLK   = 0,
            i_CPLLLOCKEN       = 1,
            i_CPLLPD           = self.cpllpd,
            o_CPLLREFCLKLOST   = Open(),
            i_CPLLREFCLKSEL    = 0b001,
            i_CPLLRESET        = tx_init.pllreset,
            i_GTRSVD           = 0b0000000000000000,
            i_PCSRSVDIN        = 0b0000000000000000,
            i_PCSRSVDIN2       = 0b00000,
            i_PMARSVDIN        = 0b00000,
            i_PMARSVDIN2       = 0b00000,
            i_TSTIN            = 0b11111111111111111111,
            o_TSTOUT           = Open(),

            # Channel
            i_CLKRSVD          = oobclk,

            # Channel - Clocking Ports
            i_GTGREFCLK        = 0,
            i_GTNORTHREFCLK0   = 0,
            i_GTNORTHREFCLK1   = 0,
            i_GTREFCLK0        = self.gtrefclk0,
            i_GTREFCLK1        = 0,
            i_GTSOUTHREFCLK0   = 0,
            i_GTSOUTHREFCLK1   = 0,

            # Channel - DRP Ports
            i_DRPADDR          = 0,
            i_DRPCLK           = 0,
            i_DRPDI            = 0,
            o_DRPDO            = Open(),
            i_DRPEN            = 0,
            o_DRPRDY           = Open(),
            i_DRPWE            = 0,

            # Clocking Ports
            o_GTREFCLKMONITOR  = Open(),
            i_QPLLCLK          = self.qpllclk,
            i_QPLLREFCLK       = self.qpllrefclk,
            i_RXSYSCLKSEL      = 0b00,
            i_TXSYSCLKSEL      = 0b00,

            # Digital Monitor Ports
            o_DMONITOROUT      = Open(),

            # FPGA TX Interface Datapath Configuration
            i_TX8B10BEN        = 1,

            # Loopback Ports
            i_LOOPBACK         = 0,

            # PCI Express Ports
            o_PHYSTATUS        = Open(),
            i_RXRATE           = 0b000,
            o_RXVALID          = Open(),

            # Power-Down Ports
            i_RXPD             = Replicate(self.rxpd, 2),
            i_TXPD             = Replicate(txpd, 2),

            # RX 8B/10B Decoder Ports
            i_SETERRSTATUS     = 0,

            # RX Initialization and Reset Ports
            i_EYESCANRESET     = 0,
            i_RXUSERRDY        = rx_init.Xxuserrdy,

            # RX Margin Analysis Ports
            o_EYESCANDATAERROR = Open(),
            i_EYESCANMODE      = 0,
            i_EYESCANTRIGGER   = 0,

            # Receive Ports - CDR Ports
            i_RXCDRFREQRESET   = 0,
            i_RXCDRHOLD        = self.rx_cdrhold,
            o_RXCDRLOCK        = Open(),
            i_RXCDROVRDEN      = 0,
            i_RXCDRRESET       = 0,
            i_RXCDRRESETRSV    = 0,

            # Receive Ports - Clock Correction Ports
            o_RXCLKCORCNT      = Open(),

            # Receive Ports - FPGA RX Interface Datapath Configuration
            i_RX8B10BEN        = 1,

            # Receive Ports - FPGA RX Interface Ports
            i_RXUSRCLK         = self.rxusrclk,
            i_RXUSRCLK2        = self.rxusrclk2,

            # Receive Ports - FPGA RX interface Ports
            o_RXDATA           = self.rxdata,

            # Receive Ports - Pattern Checker Ports
            o_RXPRBSERR        = Open(),
            i_RXPRBSSEL        = 0b000,

            # Receive Ports - Pattern Checker ports
            i_RXPRBSCNTRESET   = 0,

            # Receive Ports - RX  Equalizer Ports
            i_RXDFEXYDEN       = 1,
            i_RXDFEXYDHOLD     = 0,
            i_RXDFEXYDOVRDEN   = 0,

            # Receive Ports - RX 8B/10B Decoder Ports
            o_RXDISPERR        = rxdisperr,
            o_RXNOTINTABLE     = rxnotintable,

            # Receive Ports - RX AFE
            i_GTXRXP           = pads.rxp,
            i_GTXRXN           = pads.rxn,

            # Receive Ports - RX Buffer Bypass Ports
            i_RXBUFRESET       = 0,
            o_RXBUFSTATUS      = Open(),
            i_RXDDIEN          = 0 if rx_buffer_enable else 1,
            i_RXDLYBYPASS      = 1 if rx_buffer_enable else 0,
            i_RXDLYEN          = 0,
            i_RXDLYOVRDEN      = 0,
            i_RXDLYSRESET      = rx_init.Xxdlysreset,
            o_RXDLYSRESETDONE  = rx_init.Xxdlysresetdone,
            i_RXPHALIGN        = 0,
            o_RXPHALIGNDONE    = rx_init.Xxphaligndone,
            i_RXPHALIGNEN      = 0,
            i_RXPHDLYPD        = 0,
            i_RXPHDLYRESET     = 0,
            o_RXPHMONITOR      = Open(),
            i_RXPHOVRDEN       = 0,
            o_RXPHSLIPMONITOR  = Open(),
            o_RXSTATUS         = Open(),

            # Receive Ports - RX Byte and Word Alignment Ports
            o_RXBYTEISALIGNED  = Open(),
            o_RXBYTEREALIGN    = Open(),
            o_RXCOMMADET       = Open(),
            i_RXCOMMADETEN     = 1,
            i_RXMCOMMAALIGNEN  = 1,
            i_RXPCOMMAALIGNEN  = 1,

            # Receive Ports - RX Channel Bonding Ports
            o_RXCHANBONDSEQ    = Open(),
            i_RXCHBONDEN       = 0,
            i_RXCHBONDLEVEL    = 0b000,
            i_RXCHBONDMASTER   = 0,
            o_RXCHBONDO        = Open(),
            i_RXCHBONDSLAVE    = 0,

            # Receive Ports - RX Channel Bonding Ports
            o_RXCHANISALIGNED  = Open(),
            o_RXCHANREALIGN    = Open(),

            # Receive Ports - RX Equailizer Ports
            i_RXLPMHFHOLD      = 0,
            i_RXLPMHFOVRDEN    = 0,
            i_RXLPMLFHOLD      = 0,

            # Receive Ports - RX Equalizer Ports
            i_RXDFEAGCHOLD     = 0,
            i_RXDFEAGCOVRDEN   = 0,
            i_RXDFECM1EN       = 0,
            i_RXDFELFHOLD      = 0,
            i_RXDFELFOVRDEN    = 0,
            i_RXDFELPMRESET    = 0,
            i_RXDFETAP2HOLD    = 0,
            i_RXDFETAP2OVRDEN  = 0,
            i_RXDFETAP3HOLD    = 0,
            i_RXDFETAP3OVRDEN  = 0,
            i_RXDFETAP4HOLD    = 0,
            i_RXDFETAP4OVRDEN  = 0,
            i_RXDFETAP5HOLD    = 0,
            i_RXDFETAP5OVRDEN  = 0,
            i_RXDFEUTHOLD      = 0,
            i_RXDFEUTOVRDEN    = 0,
            i_RXDFEVPHOLD      = 0,
            i_RXDFEVPOVRDEN    = 0,
            i_RXDFEVSEN        = 0,
            i_RXLPMLFKLOVRDEN  = 0,
            o_RXMONITOROUT     = Open(),
            i_RXMONITORSEL     = 0,
            i_RXOSHOLD         = 0,
            i_RXOSOVRDEN       = 0,

            # Receive Ports - RX Fabric ClocK Output Control Ports
            o_RXRATEDONE       = Open(),

            # Receive Ports - RX Fabric Output Control Ports
            o_RXOUTCLK         = self.rxoutclk,
            o_RXOUTCLKFABRIC   = Open(),
            o_RXOUTCLKPCS      = Open(),
            i_RXOUTCLKSEL      = 0b010,

            # Receive Ports - RX Gearbox Ports
            o_RXDATAVALID      = Open(),
            o_RXHEADER         = Open(),
            o_RXHEADERVALID    = Open(),
            o_RXSTARTOFSEQ     = Open(),

            # Receive Ports - RX Gearbox Ports
            i_RXGEARBOXSLIP    = 0,

            # Receive Ports - RX Initialization and Reset Ports
            i_GTRXRESET        = rx_init.gtXxreset,
            i_RXOOBRESET       = 0,
            i_RXPCSRESET       = 0,
            i_RXPMARESET       = 0,

            # Receive Ports - RX Margin Analysis ports
            i_RXLPMEN          = 1,

            # Receive Ports - RX OOB Signaling ports
            o_RXCOMSASDET      = Open(),
            o_RXCOMWAKEDET     = rxcomwakedet,

            # Receive Ports - RX OOB Signaling ports
            o_RXCOMINITDET     = rxcominitdet,

            # Receive Ports - RX OOB signalling Ports
            o_RXELECIDLE       = Open(),
            i_RXELECIDLEMODE   = 0b00,

            # Receive Ports - RX Polarity Control Ports
            i_RXPOLARITY       = 0,

            # Receive Ports - RX gearbox ports
            i_RXSLIDE          = 0,

            # Receive Ports - RX8B/10B Decoder Ports
            o_RXCHARISCOMMA    = Open(),
            o_RXCHARISK        = self.rxcharisk,

            # Receive Ports - Rx Channel Bonding Ports
            i_RXCHBONDI        = 0b00000,

            # Receive Ports -RX Initialization and Reset Ports
            o_RXRESETDONE      = rx_init.Xxresetdone,

            # Rx AFE Ports
            i_RXQPIEN          = 0,
            o_RXQPISENN        = Open(),
            o_RXQPISENP        = Open(),

            # TX Buffer Bypass Ports
            i_TXPHDLYTSTCLK    = 0,

            # TX Configurable Driver Ports
            i_TXPOSTCURSOR     = 0b00000,
            i_TXPOSTCURSORINV  = 0,
            i_TXPRECURSOR      = 0b00000,
            i_TXPRECURSORINV   = 0,
            i_TXQPIBIASEN      = 0,
            i_TXQPISTRONGPDOWN = 0,
            i_TXQPIWEAKPUP     = 0,

            # TX Initialization and Reset Ports
            i_CFGRESET         = 0,
            i_GTTXRESET        = tx_init.gtXxreset,
            o_PCSRSVDOUT       = Open(),
            i_TXUSERRDY        = tx_init.Xxuserrdy,

            # Transceiver Reset Mode Operation
            i_GTRESETSEL       = 0,
            i_RESETOVRD        = 0,

            # Transmit Ports - 8b10b Encoder Control Ports
            i_TXCHARDISPMODE   = 0,
            i_TXCHARDISPVAL    = 0,

            # Transmit Ports - FPGA TX Interface Ports
            i_TXUSRCLK         = self.txusrclk,
            i_TXUSRCLK2        = self.txusrclk2,

            # Transmit Ports - PCI Express Ports
            i_TXELECIDLE       = txelecidle,
            i_TXMARGIN         = 0b000,
            i_TXRATE           = 0b000,
            i_TXSWING          = 0,

            # Transmit Ports - Pattern Generator Ports
            i_TXPRBSFORCEERR   = 0,

            # Transmit Ports - TX Buffer Bypass Ports
            i_TXDLYBYPASS      = 0,
            i_TXDLYEN          = 0,
            i_TXDLYHOLD        = 0,
            i_TXDLYOVRDEN      = 0,
            i_TXDLYSRESET      = tx_init.Xxdlysreset,
            o_TXDLYSRESETDONE  = tx_init.Xxdlysresetdone,
            i_TXDLYUPDOWN      = 0,
            i_TXPHALIGN        = 0,
            o_TXPHALIGNDONE    = tx_init.Xxphaligndone,
            i_TXPHALIGNEN      = 0,
            i_TXPHDLYPD        = 0,
            i_TXPHDLYRESET     = 0,
            i_TXPHINIT         = 0,
            o_TXPHINITDONE     = Open(),
            i_TXPHOVRDEN       = 0,

            # Transmit Ports - TX Buffer Ports
            o_TXBUFSTATUS      = Open(),

            # Transmit Ports - TX Configurable Driver Ports
            i_TXBUFDIFFCTRL    = 0b100,
            i_TXDEEMPH         = 0,
            i_TXDIFFCTRL       = 0b1000,
            i_TXDIFFPD         = 0,
            i_TXINHIBIT        = 0,
            i_TXMAINCURSOR     = 0b0000000,
            i_TXPISOPD         = 0,

            # Transmit Ports - TX Data Path interface
            i_TXDATA           = self.txdata,

            # Transmit Ports - TX Driver and OOB signaling
            o_GTXTXP           = pads.txp,
            o_GTXTXN           = pads.txn,

            # Transmit Ports - TX Fabric Clock Output Control Ports
            o_TXOUTCLK         = self.txoutclk,
            o_TXOUTCLKFABRIC   = Open(),
            o_TXOUTCLKPCS      = Open(),
            i_TXOUTCLKSEL      = 0b010 if tx_buffer_enable else 0b011,
            o_TXRATEDONE       = Open(),

            # Transmit Ports - TX Gearbox Ports
            i_TXCHARISK        = self.txcharisk,
            o_TXGEARBOXREADY   = Open(),
            i_TXHEADER         = 0b000,
            i_TXSEQUENCE       = 0b0000000,
            i_TXSTARTSEQ       = 0,

            # Transmit Ports - TX Initialization and Reset Ports
            i_TXPCSRESET       = 0,
            i_TXPMARESET       = 0,
            o_TXRESETDONE      = tx_init.Xxresetdone,

            # Transmit Ports - TX OOB signaling Ports
            o_TXCOMFINISH      = txcomfinish,
            i_TXCOMINIT        = txcominit,
            i_TXCOMSAS         = 0,
            i_TXCOMWAKE        = txcomwake,
            i_TXPDELECIDLEMODE = 0,

            # Transmit Ports - TX Polarity Control Ports
            i_TXPOLARITY       = 0,

            # Transmit Ports - TX Receiver Detection Ports
            i_TXDETECTRX       = 0,

            # Transmit Ports - TX8b/10b Encoder Ports
            i_TX8B10BBYPASS    = 0b00000000,

            # Transmit Ports - pattern Generator Ports
            i_TXPRBSSEL        = 0b000,

            # Tx Configurable Driver  Ports
            o_TXQPISENN        = Open(),
            o_TXQPISENP        = Open(),
        )
        self.specials += Instance("GTXE2_CHANNEL", **gtx_params)
