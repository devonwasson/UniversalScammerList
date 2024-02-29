import os
import subprocess
import sys
sys.path.insert(0, '.')
import Config

subnames = [x.split(".")[0] for x in os.listdir("config/")]
ps_output = [x for x in os.popen('ps -ef | grep python3\ runner_usl.py\ ').read().splitlines() if 'grep' not in x]
for subname in subnames:
	if subname == 'funkoppopmod':
		continue
	if not any([x.endswith(" " + subname) for x in ps_output]):
		config = Config.Config(subname)
		# Skip running on subs without read and write access
		if not config.read_from and not config.write_to:
			continue
		subprocess.Popen(['python3', 'runner_usl.py', subname])
