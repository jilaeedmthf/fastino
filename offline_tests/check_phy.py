"""Run the actual PHY and prove clear/status disconnects fail its assertions."""
from pathlib import Path
import subprocess
import sys

output, cells = map(Path, sys.argv[1:3])
iverilog, vvp = sys.argv[3:5]
root = Path(__file__).resolve().parent
source = (output / 'actual_phy.v').read_text()
mutations = {
    'actual': (None, None, None),
    'broken_clear': ('assign dac_clr_n = (~((cfg_dac_clr | spi_rst) | multispi_startup_clear));',
                     "assign dac_clr_n = 1'b1;", 'PHY clear not asserted during reset'),
    'broken_history': ('assign unlock = multiregimpl01;',
                       "assign unlock = 1'b0;", 'PHY status ready/history'),
}
for name, (before, after, expected_failure) in mutations.items():
    text = source
    if before:
        if text.count(before) != 1:
            raise RuntimeError('Generated RTL changed; inspect negative-control target: ' + name)
        text = text.replace(before, after)
    rtl, binary, log = (output / (name + suffix) for suffix in ('.v', '.vvp', '.log'))
    rtl.write_text(text)
    subprocess.run([iverilog, '-g2012', '-s', 'tb_phy', '-I', str(output),
                    '-o', str(binary), str(rtl), str(cells),
                    str(root / 'ad5542a_model.sv'), str(root / 'tb_phy.sv')], check=True)
    result = subprocess.run([vvp, str(binary)], capture_output=True, text=True)
    log.write_text(result.stdout + result.stderr)
    if expected_failure:
        if result.returncode == 0 or expected_failure not in log.read_text():
            raise RuntimeError('Negative control did not fail as expected: ' + name)
        print('PASS actual-PHY negative control:', name, flush=True)
    else:
        print(result.stdout, end='', flush=True)
        result.check_returncode()
