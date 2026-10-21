# Tektronix TBS1000B / TBS1102B verified control catalog

Extracted from the previously validated TBS1102B catalog (2026-04-22).
Only operations marked **supported** (verified on live hardware) are listed.

This is maintainer reference material for keys the driver does not model yet.
Workflows use intent verbs; use `scope.py scpi "<command>" [--query]` only to
verify a command before turning it into a dialect method. Placeholders are
shown as `<value>`.
Guarded/destructive operations (autoset, reset, calibration, save/recall, filesystem) are intentionally omitted.

| group | key | ops | query | set/action | notes |
|---|---|---|---|---|---|
| vertical | channel.bandwidth | set | CH{channel_number}:BANdwidth? | CH{channel_number}:BANdwidth {value} |  |
| vertical | channel.coupling | set | CH{channel_number}:COUPling? | CH{channel_number}:COUPling {value} |  |
| vertical | channel.current_probe | set | CH{channel_number}:CURRENTPRObe? | CH{channel_number}:CURRENTPRObe {value} |  |
| vertical | channel.invert | set | CH{channel_number}:INVert? | CH{channel_number}:INVert {value} |  |
| vertical | channel.position | set | CH{channel_number}:POSition? | CH{channel_number}:POSition {value} |  |
| vertical | channel.probe | set | CH{channel_number}:PRObe? | CH{channel_number}:PRObe {value} |  |
| vertical | channel.scale | set | CH{channel_number}:SCAle? | CH{channel_number}:SCAle {value} |  |
| vertical | channel.yunit | set | CH{channel_number}:YUNit? | CH{channel_number}:YUNit {value} |  |
| counter | counter.channel.level | set | COUNTERFreq:CH{channel_number}Level? | COUNTERFreq:CH{channel_number}Level {value} |  |
| counter | counter.channel.state | set | COUNTERFreq:CH{channel_number}State? | COUNTERFreq:CH{channel_number}State {value} |  |
| cursor | cursor | set | CURSor? | CURSor {value} |  |
| cursor | cursor.hbars.position | set | CURSor:HBArs:POSITION{index}? | CURSor:HBArs:POSITION{index} {value} |  |
| cursor | cursor.select.source | set | CURSor:SELect:SOUrce? | CURSor:SELect:SOUrce {value} |  |
| cursor | cursor.vbars.position | set | CURSor:VBArs:POSITION{index}? | CURSor:VBArs:POSITION{index} {value} |  |
| cursor | cursor.vbars.units | set | CURSor:VBArs:UNIts? | CURSor:VBArs:UNIts {value} |  |
| datalogging | datalogging.duration | set | DATALOGging:DURAtion? | DATALOGging:DURAtion {value} |  |
| datalogging | datalogging.source | set | DATALOGging:SOURCE? | DATALOGging:SOURCE {value} |  |
| datalogging | datalogging.state | set | DATALOGging:STATE? | DATALOGging:STATE {value} |  |
| display | display.backlight | set | DISplay:BACKLight? | DISplay:BACKLight {value} |  |
| display | display.format | set | DISplay:FORMat? | DISplay:FORMat {value} |  |
| display | display.persistence | set | DISplay:PERSistence? | DISplay:PERSistence {value} |  |
| display | display.style | set | DISplay:STYle? | DISplay:STYle {value} |  |
| fft | fft.horizontal.position | set | FFT:HORizontal:POSition? | FFT:HORizontal:POSition {value} |  |
| fft | fft.horizontal.scale | set | FFT:HORizontal:SCAle? | FFT:HORizontal:SCAle {value} |  |
| fft | fft.source | set | FFT:SOURce? | FFT:SOURce {value} |  |
| fft | fft.source_waveform | set | FFT:SRCWFM? | FFT:SRCWFM {value} |  |
| fft | fft.vertical.position | set | FFT:VERtical:POSition? | FFT:VERtical:POSition {value} |  |
| fft | fft.vertical.scale | set | FFT:VERtical:SCAle? | FFT:VERtical:SCAle {value} |  |
| fft | fft.window | set | FFT:WIN? | FFT:WIN {value} |  |
| filesystem | filesystem.cwd | set | FILESystem:CWD? | FILESystem:CWD {value} |  |
| hardcopy | hardcopy.button | set | HARDCopy:BUTTON? | HARDCopy:BUTTON {value} |  |
| hardcopy | hardcopy.format | set | HARDCopy:FORMat? | HARDCopy:FORMat {value} |  |
| hardcopy | hardcopy.inksaver | set | HARDCopy:INKSaver? | HARDCopy:INKSaver {value} |  |
| hardcopy | hardcopy.layout | set | HARDCopy:LAYout? | HARDCopy:LAYout {value} |  |
| hardcopy | hardcopy.port | set | HARDCopy:PORT? | HARDCopy:PORT {value} |  |
| horizontal | horizontal.main.position | set | HORizontal:MAIn:POSition? | HORizontal:MAIn:POSition {value} |  |
| horizontal | horizontal.main.scale | set | HORizontal:MAIn:SCAle? | HORizontal:MAIn:SCAle {value} |  |
| horizontal | horizontal.position | set | HORizontal:POSition? | HORizontal:POSition {value} |  |
| limit | limit.save_image | set | LIMit:SAVEIMAge? | LIMit:SAVEIMAge {value} |  |
| limit | limit.save_waveform | set | LIMit:SAVEWFM? | LIMit:SAVEWFM {value} |  |
| limit | limit.source | set | LIMit:SOUrce? | LIMit:SOUrce {value} |  |
| limit | limit.state | set | LIMit:STATE? | LIMit:STATE {value} |  |
| limit | limit.stopafter.mode | set | LIMit:STOPAfter:MODe? | LIMit:STOPAfter:MODe {value} |  |
| limit | limit.stopafter.time | set | LIMit:STOPAfter:TIMe? | LIMit:STOPAfter:TIMe {value} |  |
| limit | limit.stopafter.violation | set | LIMit:STOPAfter:VIOLation? | LIMit:STOPAfter:VIOLation {value} |  |
| limit | limit.stopafter.waveform | set | LIMit:STOPAfter:WAVEform? | LIMit:STOPAfter:WAVEform {value} |  |
| limit | limit.template.dual_source | set | LIMit:TEMPlate:DUALSOUrce? | LIMit:TEMPlate:DUALSOUrce {value} |  |
| limit | limit.template.source | set | LIMit:TEMPLate:SOUrce? | LIMit:TEMPLate:SOUrce {value} |  |
| limit | limit.template.tolerance.horizontal | set | LIMit:TEMPLate:TOLerance:HORizontal? | LIMit:TEMPLate:TOLerance:HORizontal {value} |  |
| limit | limit.template.tolerance.vertical | set | LIMit:TEMPLate:TOLerance:VERTical? | LIMit:TEMPLate:TOLerance:VERTical {value} |  |
| math | math.define | set | MATH:DEFINE? | MATH:DEFINE {value} |  |
| math | math.vertical.position | set | MATH:VERtical:POSition? | MATH:VERtical:POSition {value} |  |
| math | math.vertical.scale | set | MATH:VERtical:SCAle? | MATH:VERtical:SCAle {value} |  |
| measurement | measurement.clear_snapshot | action |  | MEASUrement:CLEARSNAPSHOT |  |
| measurement | measurement.gating | set | MEASUrement:GATing? | MEASUrement:GATing {value} |  |
| measurement | measurement.immediate.source | set | MEASUrement:IMMed:SOUrce? | MEASUrement:IMMed:SOUrce {value} |  |
| measurement | measurement.immediate.type | set | MEASUrement:IMMed:TYPe? | MEASUrement:IMMed:TYPe {value} |  |
| measurement | measurement.slot.source | set | MEASUrement:MEAS{slot}:SOUrce? | MEASUrement:MEAS{slot}:SOUrce {value} |  |
| measurement | measurement.slot.type | set | MEASUrement:MEAS{slot}:TYPe? | MEASUrement:MEAS{slot}:TYPe {value} |  |
| measurement | measurement.snapshot | action |  | MEASUrement:SNAPSHOT |  |
| measurement | measurement.snapshot.source | set | MEASUrement:SNAPSOUrce? | MEASUrement:SNAPSOUrce {value} |  |
| pictbridge | pictbridge.date_print | set | PICTBridge:DATEPRINT? | PICTBridge:DATEPRINT {value} |  |
| pictbridge | pictbridge.id_print | set | PICTBridge:IDPRINT? | PICTBridge:IDPRINT {value} |  |
| pictbridge | pictbridge.image_size | set | PICTBridge:IMAGESIZE? | PICTBridge:IMAGESIZE {value} |  |
| pictbridge | pictbridge.paper_size | set | PICTBridge:PAPERSIZE? | PICTBridge:PAPERSIZE {value} |  |
| pictbridge | pictbridge.paper_type | set | PICTBridge:PAPERTYPE? | PICTBridge:PAPERTYPE {value} |  |
| pictbridge | pictbridge.print_quality | set | PICTBridge:PRINTQUAL? | PICTBridge:PRINTQUAL {value} |  |
| save | save.image.file_format | set | SAVe:IMAge:FILEFormat? | SAVe:IMAge:FILEFormat {value} |  |
| vertical | select.waveform | set | SELect:{waveform}? | SELect:{waveform} {value} |  |
| status | status.clear | action |  | *CLS |  |
| status | status.dese | set | DESE? | DESE {value} |  |
| status | status.ese | set | *ESE? | *ESE {value} |  |
| status | status.operation_complete | action | *OPC? | *OPC |  |
| status | status.psc | set | *PSC? | *PSC {value} |  |
| status | status.sre | set | *SRE? | *SRE {value} |  |
| status | status.wait | action |  | *WAI |  |
| system | system.autorange.settings | set | AUTORange:SETTings? | AUTORange:SETTings {value} |  |
| system | system.autorange.state | set | AUTORange:STATE? | AUTORange:STATE {value} |  |
| system | system.autoset.view | set | AUTOSet:VIEW? | AUTOSet:VIEW {value} |  |
| system | system.date | set | DATE? | DATE {value} |  |
| system | system.header | set | HEADer? | HEADer {value} |  |
| system | system.language | set | LANGuage? | LANGuage {value} |  |
| system | system.lock | action |  | LOCk |  |
| system | system.time | set | TIMe? | TIMe {value} |  |
| system | system.trigger | action |  | *TRG |  |
| system | system.unlock | action |  | UNLock |  |
| system | system.verbose | set | VERBose? | VERBose {value} |  |
| trendplot | trendplot.slot.source | set | TRENDPLOT:TP{slot}:SOURCE? | TRENDPLOT:TP{slot}:SOURCE {value} |  |
| trendplot | trendplot.slot.type | set | TRENDPLOT:TP{slot}:TYPe? | TRENDPLOT:TP{slot}:TYPe {value} |  |
| trigger | trigger.force | action |  | TRIGger |  |
| trigger | trigger.main | action | TRIGger:MAIn? | TRIGger:MAIn |  |
| trigger | trigger.main.edge.coupling | set | TRIGger:MAIn:EDGE:COUPling? | TRIGger:MAIn:EDGE:COUPling {value} |  |
| trigger | trigger.main.edge.slope | set | TRIGger:MAIn:EDGE:SLOpe? | TRIGger:MAIn:EDGE:SLOpe {value} |  |
| trigger | trigger.main.edge.source | set | TRIGger:MAIn:EDGE:SOUrce? | TRIGger:MAIn:EDGE:SOUrce {value} |  |
| trigger | trigger.main.holdoff.value | set | TRIGger:MAIn:HOLDOff:VALue? | TRIGger:MAIn:HOLDOff:VALue {value} |  |
| trigger | trigger.main.level | set | TRIGger:MAIn:LEVel? | TRIGger:MAIn:LEVel {value} |  |
| trigger | trigger.main.mode | set | TRIGger:MAIn:MODe? | TRIGger:MAIn:MODe {value} |  |
| trigger | trigger.main.pulse.source | set | TRIGger:MAIn:PULse:SOUrce? | TRIGger:MAIn:PULse:SOUrce {value} |  |
| trigger | trigger.main.pulse.width.polarity | set | TRIGger:MAIn:PULse:WIDth:POLarity? | TRIGger:MAIn:PULse:WIDth:POLarity {value} |  |
| trigger | trigger.main.pulse.width.value | set | TRIGger:MAIn:PULse:WIDth:WIDth? | TRIGger:MAIn:PULse:WIDth:WIDth {value} |  |
| trigger | trigger.main.pulse.width.when | set | TRIGger:MAIn:PULse:WIDth:WHEN? | TRIGger:MAIn:PULse:WIDth:WHEN {value} |  |
| trigger | trigger.main.type | set | TRIGger:MAIn:TYPe? | TRIGger:MAIn:TYPe {value} |  |
| trigger | trigger.main.video.line | set | TRIGger:MAIn:VIDeo:LINE? | TRIGger:MAIn:VIDeo:LINE {value} |  |
| trigger | trigger.main.video.polarity | set | TRIGger:MAIn:VIDeo:POLarity? | TRIGger:MAIn:VIDeo:POLarity {value} |  |
| trigger | trigger.main.video.source | set | TRIGger:MAIn:VIDeo:SOUrce? | TRIGger:MAIn:VIDeo:SOUrce {value} |  |
| trigger | trigger.main.video.standard | set | TRIGger:MAIn:VIDeo:STANDard? | TRIGger:MAIn:VIDeo:STANDard {value} |  |
| trigger | trigger.main.video.sync | set | TRIGger:MAIn:VIDeo:SYNC? | TRIGger:MAIn:VIDeo:SYNC {value} |  |
| waveform | waveform.data | set | DATa? | DATa {value} |  |
| waveform | waveform.data.destination | set | DATa:DESTination? | DATa:DESTination {value} |  |
| waveform | waveform.data.encoding | set | DATa:ENCdg? | DATa:ENCdg {value} |  |
| waveform | waveform.data.source | set | DATa:SOUrce? | DATa:SOUrce {value} |  |
| waveform | waveform.data.start | set | DATa:STARt? | DATa:STARt {value} |  |
| waveform | waveform.data.stop | set | DATa:STOP? | DATa:STOP {value} |  |
| waveform | waveform.data.width | set | DATa:WIDth? | DATa:WIDth {value} |  |
| waveform | waveform.preamble.bit_nr | set | WFMPre:BIT_Nr? | WFMPre:BIT_Nr {value} |  |
| waveform | waveform.preamble.bn_fmt | set | WFMPre:BN_Fmt? | WFMPre:BN_Fmt {value} |  |
| waveform | waveform.preamble.byt_nr | set | WFMPre:BYT_Nr? | WFMPre:BYT_Nr {value} |  |
| waveform | waveform.preamble.byt_or | set | WFMPre:BYT_Or? | WFMPre:BYT_Or {value} |  |
| waveform | waveform.preamble.encoding | set | WFMPre:ENCdg? | WFMPre:ENCdg {value} |  |
| waveform | waveform.preamble.point_format | set | WFMPre:PT_Fmt? | WFMPre:PT_Fmt {value} |  |
| waveform | waveform.preamble.x_increment | set | WFMPre:XINcr? | WFMPre:XINcr {value} |  |
| waveform | waveform.preamble.x_unit | set | WFMPre:XUNit? | WFMPre:XUNit {value} |  |
| waveform | waveform.preamble.x_zero | set | WFMPre:XZEro? | WFMPre:XZEro {value} |  |
| waveform | waveform.preamble.y_multiplier | set | WFMPre:YMUlt? | WFMPre:YMUlt {value} |  |
| waveform | waveform.preamble.y_offset | set | WFMPre:YOFf? | WFMPre:YOFf {value} |  |
| waveform | waveform.preamble.y_unit | set | WFMPre:YUNit? | WFMPre:YUNit {value} |  |
| waveform | waveform.preamble.y_zero | set | WFMPre:YZEro? | WFMPre:YZEro {value} |  |

Total: 127 verified keys.
