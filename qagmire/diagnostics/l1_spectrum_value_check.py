# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/diagnostics/13_l1_spectrum_value_check.ipynb.

# %% auto 0
__all__ = ['L1SpectrumValueCheck', 'plot_qty_and_nans']

# %% ../../nbs/diagnostics/13_l1_spectrum_value_check.ipynb 2
import matplotlib.pyplot as plt
import numpy as np

from qagmire.data import (
    get_lr_l1_single_files,
    read_l1_data,
)
from ..quality_assurance import Diagnostics

# %% ../../nbs/diagnostics/13_l1_spectrum_value_check.ipynb 4
class L1SpectrumValueCheck(Diagnostics):
    """L1 spectrum value check.

    A reproduction of the class with the same name in the weaveio
    [value_checks](https://github.com/bamford/QAG/blob/master/diagnostics/value_checks.py).

    This tests for the following cases:

    * Are there non-finite pixel values?

    for the red and blue 'flux', 'flux_noss', 'ivar', 'ivar_noss' and 'sensfunc' arrays, as well as:

    * Are there negative pixel values?

    for the red and blue 'ivar', 'ivar_noss' and 'sensfunc' arrays.
    """

    def __init__(
        self,
        n_allowed_bad: int = 0,  # the number of allowed bad pixels per spectrum
        camera=None,  # limit to a specific camera: RED or BLUE
        **kwargs,  # additional keyword arguments are passed to the `Diagnostics` constructor
    ):
        self.n_allowed_bad = n_allowed_bad
        self.camera = camera.upper() if camera is not None else None
        super().__init__(**kwargs)

    def tests(self, **kwargs):
        files = get_lr_l1_single_files(**kwargs)
        data = read_l1_data(files)

        if self.camera is not None:
            camera_match = data["CAMERA"] == self.camera
            data = data.sel(filename=camera_match)
            cameras = [self.camera]
        else:
            cameras = ["RED", "BLUE"]

        # perform the tests by RUN, rather than filename
        data = data.swap_dims(filename="RUN")
        self.data = data

        neg = data < 0
        nan = ~np.isfinite(data)

        any_neg = neg.any(dim=["LAMBDA_R", "LAMBDA_B"])
        any_nan = nan.any(dim=["LAMBDA_R", "LAMBDA_B"])

        tests = []
        for camera in cameras:
            camera_match = data["CAMERA"] == camera
            for ext in ["FLUX", "FLUX_NOSS", "IVAR", "IVAR_NOSS", "SENSFUNC"]:
                name = f"{camera}_{ext}"
                tests.append(
                    {
                        "name": f"nans_in_{name}",
                        "description": f"Are there non-finite values in {name}?",
                        "test": any_nan[name] & camera_match,
                    }
                )
            for ext in ["IVAR", "IVAR_NOSS", "SENSFUNC"]:
                name = f"{camera}_{ext}"
                tests.append(
                    {
                        "name": f"negs_in_{name}",
                        "description": f"Are there negative values in {name}?",
                        "test": any_neg[name] & camera_match,
                    }
                )
        return tests

# %% ../../nbs/diagnostics/13_l1_spectrum_value_check.ipynb 16
def plot_qty_and_nans(data, run, ext):
    qty = data.sel(RUN=run)[ext]
    fig, ax = plt.subplots(2, 1, figsize=(15, 4), sharex=True, sharey=True)
    ax[0].imshow(qty, vmin=0, vmax=100, interpolation="none", aspect="auto")
    ax[0].set_title(ext)
    ax[1].imshow(~np.isfinite(qty), interpolation="none", aspect="auto")
    ax[1].set_title("NaNs")
    fig.suptitle(f"RUN {run}")
    plt.tight_layout()
