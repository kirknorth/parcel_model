""" Utilities for driving sets of parcel model integration strategies. 

Occasionally, a pathological set of input parameters to the parcel model
will really muck up the hidden ODE solver's ability to integrate the model.
In that case, it would be nice to quietly adjust some of the numerical 
parameters for the ODE solver and re-submit the job. This module includes a
workhorse function **iterate_runs** which can serve this purpose and can
serve as an example for more complex strategies. Alternatively, **run_model** 
is a useful shortcut for building/running a model, and snagging its output.

"""

from numpy import empty, nan
from pandas import DataFrame

from parcel import ParcelModel, ParcelModelError
from activation import fn2005, arg2000


def run_model(V, initial_aerosols, T, P, dt, S0=-0.0, max_steps=1000, t_end=500.,
              solver='lsoda', output='smax', solver_args={}):
    """ Setup and run the parcel model with given solver configuration.

    Parameters
    ----------
    V, T, P : float
        Updraft speed and parcel initial temperature and pressure.
    S0 : float, optional, default 0.0
        Initial supersaturation, as a percent. Defaults to 100% relative humidity.
    initial_aerosols : array_like of :class:`AerosolSpecies`
        Set of aerosol populations contained in the parcel.
    dt : float
        Solver timestep, in seconds.
    max_steps : int, optional, default 1000
        Maximum number of steps per solver iteration. Defaults to 1000; setting 
        excessively high could produce extremely long computation times.
    t_end : float, optional, default 500.0
        Model time in seconds after which the integration will stop.
    solver : string, optional, default 'lsoda'
        Alias of which solver to use; see :class:`Integrator` for all options.
    output : string, optional, default 'smax'
        Alias indicating which output format to use; see :class:`ParcelModel` for
        all options.
    solver_args : dict, optional
        Detailed arguments/configuration to pass to the numerical integrator.

    Returns
    -------
    Smax : (user-defined)
        Output from parcel model simulation based on user-specified `output` argument. See
        :class:`ParcelModel` for details.

    Raises
    ------
    ParcelModelError
        If the model fails to initialize or breaks during runtime.

    """
    if V <= 0:
        return 0.

    try: 
        model = ParcelModel(initial_aerosols, V, T, S0, P)
        Smax = model.run(t_end, dt, max_steps, solver=solver, 
                         output=output, solver_args=solver_args)
    except ParcelModelError:
        return None
    return Smax

def iterate_runs(V, initial_aerosols, T, P, S0=-0.0, dt=0.01, dt_iters=2, 
                 t_end=500., max_steps=500, output='smax',
                 fail_easy=True):
    """ Iterate through several different strategies for integrating the parcel model.

    Parameters
    ----------
    V, T, P : float
        Updraft speed and parcel initial temperature and pressure.
    S0 : float, optional, default 0.0
        Initial supersaturation, as a percent. Defaults to 100% relative humidity.
    initial_aerosols : array_like of :class:`AerosolSpecies`
        Set of aerosol populations contained in the parcel.
    dt : float
        Solver timestep, in seconds.
    dt_iters : int, optional, default 2
        Number of times to halve `dt` when attempting **LSODA** solver.
    max_steps : int, optional, default 1000
        Maximum number of steps per solver iteration. Defaults to 1000; setting 
        excessively high could produce extremely long computation times.
    t_end : float, optional, default 500.0
        Model time in seconds after which the integration will stop.
    solver : string, optional, default 'lsoda'
        Alias of which solver to use; see :class:`Integrator` for all options.
    output : string, optional, default 'smax'
        Alias indicating which output format to use; see :class:`ParcelModel` for
        all options.
    fail_easy : boolean, optional, default `True`
        If `True`, then stop after the first strategy (**CVODE**)

    Returns
    -------
    Smax : (user-defined)
        Output from parcel model simulation based on user-specified `output` argument. See
        :class:`ParcelModel` for details.

    """
    aerosols = initial_aerosols
    if V <= 0:
        return 0., 0., 0.

    ## Check that there are actually aerosols to deal with
    aerosol_N = [a.distribution.N for a in initial_aerosols]
    if len(aerosol_N) == 1:
        if aerosol_N[0] < 0.01: return (-9999., -9999., -9999.)
    else:
        new_aerosols = []
        for i in xrange(len(aerosol_N)):
            if aerosol_N[i] > 0.01: 
                new_aerosols.append(initial_aerosols[i])
        aerosols = new_aerosols[:]

    S_max_arg, _ = arg2000(V, T, P, aerosols)
    S_max_fn, _ = fn2005(V, T, P, aerosols)

    dt_orig = dt*1.
    finished = False
    S_max = None

    ## Strategy 1: Try CVODE with modest tolerances.
    print " Trying CVODE with default tolerance"
    S_max = run_model(V, aerosols, T, P, dt, S0=S0, max_steps=2000, solver='cvode',
                      t_end=t_end, output=output, 
                      solver_args={'iter': 'Newton', 'time_limit': 10.0, 
                                   'linear_solver': "DENSE"})

    ## Strategy 2: Iterate over some increasingly relaxed tolerances for LSODA.
    if not S_max and not fail_easy:
        while dt > dt_orig/(2**dt_iters):
            print " Trying LSODA, dt = %1.3e, max_steps = %d" % (dt, max_steps)
            S_max = run_model(V, aerosols, T, P, dt, max_steps, solver='lsoda',
                              t_end=t_end, S0=S0)
            if not S_max:
                dt = dt/2.
                print "    Retrying..."
            else:
                finished = True
                break

    ## Strategy 3: Last ditch numerical integration with LSODE. This will likely take a
    ##             a very long time.
    if not finished and not S_max and not fail_easy:
        print " Trying LSODE"
        S_max = run_model(V, aerosols, T, P, dt_orig, max_steps=1000, solver='lsode',
                          t_end=t_end, S0=S0)

    ## Strategy 4: If all else fails return -9999.
    if not S_max:
        if output == "smax":
            S_max = -9999.
        elif output == "arrays":
            S_max = empty([0]), empty([0])
        elif output == "dataframes":
            S_max = DataFrame(data={"S": [nan]}), DataFrame(data={"aerosol1": [nan]})
        else:
            S_max = nan
        print " failed", V, dt

    return S_max, S_max_arg, S_max_fn
