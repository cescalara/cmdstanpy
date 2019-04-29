import os
import os.path
import subprocess
from multiprocessing import cpu_count
from multiprocessing.pool import ThreadPool

from .config import CMDSTAN_PATH
from .lib import Model, RunSet, SamplerArgs
from .utils import is_int


def compile_model(stan_file, opt_lvl=3, overwrite=False):
    """Compile the given Stan model file to an executable.
    """
    if not os.path.exists(stan_file):
        raise Exception('no such stan_file {}'.format(stan_file))
    path = os.path.abspath(os.path.dirname(stan_file))
    program_name = os.path.basename(stan_file)
    model_name = program_name[:-5]

    hpp_name = model_name + '.hpp'
    hpp_file = os.path.join(path, hpp_name)
    if overwrite or not os.path.exists(hpp_file):
        print('translating to {}'.format(hpp_file))
        stanc_path = os.path.join(CMDSTAN_PATH, 'bin', 'stanc')
        cmd = [stanc_path, '--o={}'.format(hpp_file), stan_file]
        print('stan to c++: make args {}'.format(cmd))
        do_command(cmd)
        if not os.path.exists(hpp_file):
            raise Exception('syntax error'.format(stan_file))

    exe_file = os.path.join(path, model_name)
    if not overwrite and os.path.exists(exe_file):
        # print('model is up to date') # notify user or not?
        return Model(stan_file, model_name, exe_file)

    cmd = ['make', 'O={}'.format(opt_lvl), exe_file]
    print('compiling c++: make args {}'.format(cmd))
    try:
        do_command(cmd, CMDSTAN_PATH)
    except Exception:
        return Model(stan_file, model_name)
    return Model(stan_file, model_name, exe_file)


def sample(stan_model=None,
           chains=4,
           cores=1,
           seed=None,
           data_file=None,
           init_param_values=None,
           csv_output_file=None,
           console_output_file=None,
           refresh=None,
           post_warmup_draws_per_chain=None,
           warmup_draws_per_chain=None,
           save_warmup=False,
           thin=None,
           do_adaptation=True,
           adapt_gamma=None,
           adapt_delta=None,
           adapt_kappa=None,
           adapt_t0=None,
           nuts_max_depth=None,
           hmc_metric=None,
           hmc_metric_file=None,
           hmc_stepsize=1):
    """Runs on or more chains of the NUTS/HMC sampler."""
    args = SamplerArgs(model=stan_model,
                       seed=seed,
                       data_file=data_file,
                       init_param_values=init_param_values,
                       output_file=csv_output_file,
                       refresh=refresh,
                       post_warmup_draws=post_warmup_draws_per_chain,
                       warmup_draws=warmup_draws_per_chain,
                       save_warmup=save_warmup,
                       thin=thin,
                       do_adaptation=do_adaptation,
                       adapt_gamma=adapt_gamma,
                       adapt_delta=adapt_delta,
                       adapt_kappa=adapt_kappa,
                       adapt_t0=adapt_t0,
                       nuts_max_depth=nuts_max_depth,
                       hmc_metric_file=hmc_metric_file,
                       hmc_stepsize=hmc_stepsize)
    args.validate()
    if not is_int(chains) and chains > 0:
        raise ValueError(
            'chains must be a positive integer value, found {}'.format(chains))
    if not is_int(cores) and cores > 0:
        raise ValueError(
            'cores must be a positive integer value, found {}'.format(cores))
    if cores > cpu_count():
        print('requested {} cores, only {} available'.format(
            cores, cpu_count()))
        cores = cpu_count()
    runset = RunSet(args=args,
                    chains=chains,
                    cores=cores,
                    console_file=console_output_file)
    tp = ThreadPool(cores)
    for i in range(chains):
        tp.apply_async(do_sample, (
            runset,
            i,
        ))
    tp.close()
    tp.join()
    if not runset.check_retcodes():
        msg = "Error during sampling"
        for i in range(chains):
            if runset.get_retcode(i) != 0:
                msg = '{}, chain {} returned error code {}'.format(
                    msg, i, runset.get_retcode(i))
        raise Exception(msg)
    # runset.check_console_msgs()
    return runset


def summary(runset=None, filename=None, sig_figs=None):
    if runset is None:
        raise ValueError('summary command requires specified RunSet from sampler')
    cmd_path = os.path.join(CMDSTAN_PATH, 'bin', 'stansummary')
    csv_files = ' '.join(runset.output_files)
    cmd = '{} {} '.format(cmd_path, csv_files, filename)
    if filename is not None:
        print('summary output file: {}'.format(filename))
        if not os.path.exists(filename):
            try:
                open(filename, 'w')
            except OSError:
                raise Exception('cannot write to file {}'.format(filename))
        else:
            raise ValueError('output file already exists: {}'.format(filename))
        cmd = '{} --csv_file={}'.format(cmd, filename)
    if sig_figs is not None:
        if not is_int(sig_figs) and sig_figs > 0:
            raise ValueError(
                'sig_figs must be a positive integer value, found {}'.format(
                    sig_figs))
        cmd = '{} --sig_figs={}'.format(cmd, sig_figs)
    print(cmd)
    proc = subprocess.Popen(
        cmd.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc.wait()
    stdout, stderr = proc.communicate()
    if stdout:
        print(stdout.decode('ascii'))
    if stderr:
        print('ERROR')
        print(stderr.decode('ascii'))
    if filename is not None:
        with open(filename, 'w') as fd:
            if stdout:
                fd.write(stdout.decode('ascii'))
                fd.write('\n')
            if stderr:
                fd.write(stderr.decode('ascii'))
                fd.write('\n')
    if proc.returncode != 0:
        raise Exception('summary cmd failed, return code: {}'.format(
            proc.returncode))


def diagnose(runset=None, filename=None):
    if runset is None:
        raise ValueError('summary command requires specified RunSet from sampler')
    print('diagnose - runset: {}'.format(runset))
    cmd_path = os.path.join(CMDSTAN_PATH, 'bin', 'diagnose')
    csv_files = ' '.join(runset.output_files)
    cmd = '{} {} '.format(cmd_path, csv_files)
    print('cmd: {}'.format(cmd))
    proc = subprocess.Popen(
        cmd.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc.wait()
    stdout, stderr = proc.communicate()
    if stdout:
        print("stdout")
        print(stdout.decode('ascii'))
    if stderr:
        print('ERROR')
        print(stderr.decode('ascii'))
    if filename is not None:
        with open(filename, 'w') as fd:
            if not (stdout and stderr):
                fd.write('Processing complete, no problems detected\n')
            else:
                if stdout:
                    fd.write(stdout.decode('ascii'))
                if stderr:
                    fd.write('ERROR\n')
                    fd.write(stderr.decode('ascii'))

    if proc.returncode != 0:
        raise Exception('summary cmd failed, return code: {}'.format(
            proc.returncode))


def do_sample(runset, idx):
    """Spawn process, capture console output to file, record returncode."""
    cmd = runset.cmds[idx]
    proc = subprocess.Popen(
        cmd.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc.wait()
    stdout, stderr = proc.communicate()
    transcript_file = runset.console_files[idx]
    with open(transcript_file, "w+") as transcript:
        if stdout:
            transcript.write(stdout.decode('ascii'))
        if stderr:
            transcript.write('ERROR')
            transcript.write(stderr.decode('ascii'))
    runset.set_retcode(idx, proc.returncode)


def do_command(cmd, cwd=None):
    """Spawn process, get output/err/returncode."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc.wait()
    stdout, stderr = proc.communicate()
    if stdout:
        print(stdout.decode('ascii').strip())
    if stderr:
        print('ERROR\n {} '.format(stderr.decode('ascii').strip()))
    if (proc.returncode):
        raise Exception('Command failed: {}'.format(cmd))
