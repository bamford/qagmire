# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/diagnostics/15_sky_noise_distribution_check.ipynb.

# %% auto 0
__all__ = ['SkyNoiseDistributionCheck']

# %% ../../nbs/diagnostics/15_sky_noise_distribution_check.ipynb 3
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import xarray as xr
from dask.distributed import Client

from ..data import get_weave_files, read_fibre_table_nspec, read_l1_data
from ..quality_assurance import Diagnostics
from ..utilities import ks_norm_prob

# %% ../../nbs/diagnostics/15_sky_noise_distribution_check.ipynb 5
class SkyNoiseDistributionCheck(Diagnostics):
    """Sky noise distribution check.

    A reproduction of the NoisePropCheck classes in the weaveio
    [noise_prop_checks](https://github.com/bamford/QAG/blob/master/diagnostics/noise_prop_checks.py).

    This tests for the following case:

    * Is the mean of the normalised flux in sky fibres significantly different from zero?
    * Is the standard deviation of the normalised flux in sky fibres significantly different from unity?
    * Does the distribution of normalised flux in sky fibres fail a KS test comparison with a standard Normal?

    for "single" and "stack" L1 spectra and for the red and blue cameras.
    """

    def __init__(
        self,
        ks_pvalue_limit: float = 0.01,  # the pvalue below which distributions are considered to differ
        mean_sig_limit: float = 5,  # the significance above which means are considered to differ
        stdev_sig_limit: float = 5,  # the significance above which stdevs are considered to differ
        stack=False,  # if True, check the stack spectra, otherwise check the single spectra
        camera=None,  # limit to a specific camera: RED or BLUE
        **kwargs,  # additional keyword arguments are passed to the `Diagnostics` constructor
    ):
        self.ks_pvalue_limit = ks_pvalue_limit
        self.mean_sig_limit = mean_sig_limit
        self.stdev_sig_limit = stdev_sig_limit
        self.stack = stack
        self.camera = camera.upper() if camera is not None else None
        super().__init__(**kwargs)

    def tests(self, **kwargs):
        filetype = "stack" if self.stack else "single"
        files = get_weave_files(level="L1", lowres=True, filetype=filetype, **kwargs)
        data = read_l1_data(files)

        fibre_table = read_fibre_table_nspec(files)
        data = xr.merge((data, fibre_table))
        data = data.where(data["TARGUSE"] == b"S", drop=True)

        if self.camera is not None:
            camera_match = data["CAMERA"] == self.camera
            data = data.sel(filename=camera_match)
            cameras = [self.camera]
        else:
            cameras = ["RED", "BLUE"]

        # perform the tests by RUN, rather than filename
        data = data.swap_dims(filename="RUN")
        self.data = data

        stats = []
        for camera in cameras:
            camera_match = data["CAMERA"] == camera
            flux, ivar = f"{camera}_FLUX", f"{camera}_IVAR"
            camdata = data[[flux, ivar]].sel(RUN=camera_match)
            camdata = camdata.where(camdata[ivar] > 0)
            camdata = camdata.stack(SPEC=("RUN", "NSPEC"))
            normflux = camdata[flux] * np.sqrt(camdata[ivar])
            exdim = [d for d in normflux.dims if d != "SPEC"][0]
            check_stats = xr.Dataset()
            n = normflux.count(exdim)
            check_stats["stdev_measured"] = camdata[flux].std(exdim, ddof=1)
            check_stats["stdev_expected"] = np.sqrt((1 / camdata[ivar]).mean(exdim))
            check_stats["mean_zscore"] = normflux.mean(exdim)
            check_stats["stdev_zscore"] = normflux.std(exdim, ddof=1)
            check_stats["err_on_mean_zscore"] = check_stats["stdev_zscore"] / np.sqrt(n)
            check_stats["err_on_stdev_zscore"] = check_stats["stdev_zscore"] / np.sqrt(
                2 * n - 2
            )
            check_stats["sig_mean_zscore"] = (
                abs(check_stats["mean_zscore"]) / check_stats["err_on_mean_zscore"]
            )
            check_stats["sig_stdev_zscore"] = (
                abs(check_stats["stdev_zscore"] - 1)
                / check_stats["err_on_stdev_zscore"]
            )
            check_stats["ks_prob"] = ks_norm_prob(normflux)
            stats.append(check_stats)
        check_stats = xr.concat(stats, "SPEC")
        self.stats = check_stats
        check_stats = check_stats.unstack("SPEC")
        # remove apparent dependence of other coords on NSPEC
        for x in check_stats.coords:
            if x not in ("RUN", "NSPEC"):
                check_stats[x] = check_stats[x].isel(NSPEC=0)

        tests = [
            {
                "name": "mean_non_zero",
                "description": "Is the mean of the normalised flux in sky fibres "
                "significantly different from zero?",
                "test": check_stats["sig_mean_zscore"] > self.mean_sig_limit,
            },
            {
                "name": "stdev_non_unit",
                "description": "Is the standard deviation of the normalised flux in "
                "sky fibres significantly different from unity?",
                "test": check_stats["sig_stdev_zscore"] > self.stdev_sig_limit,
            },
            {
                "name": "ks_non_normal",
                "description": "Does the distribution of normalised flux in sky fibres "
                "fail a KS test comparison with a standard Normal?",
                "test": check_stats["ks_prob"] < self.ks_pvalue_limit,
            },
        ]
        return tests
