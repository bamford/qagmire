# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/01_data.ipynb.

# %% auto 0
__all__ = ['via_netcdf', 'ViaNetCDF', 'get_weave_files', 'get_lr_l2_stack_files', 'read_class_table', 'read_star_table',
           'not_line_col', 'read_galaxy_table', 'read_class_spec', 'read_star_spec', 'read_galaxy_spec']

# %% ../nbs/01_data.ipynb 2
import os
import sys
import time
from functools import partial, wraps
from glob import glob
from typing import Callable

import xarray as xr
from astropy.io import fits
from astropy.table import Table
from tqdm import tqdm

# %% ../nbs/01_data.ipynb 4
class ViaNetCDF:
    """Access FITS tables as xarray Datasets via cached netCDF files.

    For each FITS table or image we wish to read, we will write a `read_*(fn)` function
    which reads the table from the single provided filename `fn` and returns a `Dataset`.
    Decorating such a function with an instance of this class adapts the function to take
    a list of FITS filenames and return a `Dataset` that lazily loads data from a cache
    of netCDF files. The cache is stored in the `netcdf_store` folder defined when the
    instance is initialised.

    When the decorated function is initially run, it repeatedly calls `single_via_netcdf`
    to apply the original `read_*` function to each FITS filename and save each resulting
    `Dataset` as a netCDF file, then opens them together and returns a combined,
    distributed `Dataset`. If a previously converted file is found in the `netcdf_store`,
    then the original `read_*` function is skipped and the netCDF file loaded directly.
    This caching vastly increase the speed of subsequent calls.

    If a source FITS file is changed, the corresponding files in `netcdf_store` can simply
    be deleted and they will be recreated on the next call of the decorated `read_*`
    function.

    For example,
    ```
    via_netcdf = ViaNetCDF()

    @via_netcdf
    def read_class_spec(fn):
        ...
    ```
    """

    def __init__(
        self,
        netcdf_store: str | None = None,  # folder in which to store the netCDF files
        progress=True,  # display a progress bar
    ):
        """Create a decorator that can extend a `read_*` function to multiple files.

        If no `netcdf_store` is provided it first checks for a `NETCDF_STORE` environment
        variable and falls back to a folder called `netcdf_store` in the user's home folder.
        """
        if netcdf_store is not None:
            self.netcdf_store = netcdf_store
        else:
            default = os.path.join(os.environ.get("HOME"), "netcdf_store")
            self.netcdf_store = os.environ.get("NETCDF_STORE", default)

        if progress:
            self.progress = partial(
                tqdm, desc="Locating and converting where necessary", file=sys.stdout
            )
        else:
            self.progress = lambda x: x

    def single_via_netcdf(
        self,
        read_function: Callable[[str], xr.Dataset],  # function to read a FITS file
        fn: str,  # filename of FITS file to read
    ):
        """Transform a FITS file to netCDF using the given read function.

        Returns the path of a netCDF file stored in `nedcdf_store`, containing the `Dataset` resulting
        from calling `read_function` with the supplied FITS filename `fn`. If the netCDF file already
        exists, the filename is immediately returned.
        """
        fn_netcdf = os.path.join(
            self.netcdf_store, *os.path.normpath(fn).split(os.sep)[-3:]
        )
        table = read_function.__name__.replace("read_", "")
        fn_netcdf = os.path.splitext(fn_netcdf)[0]
        fn_netcdf = f"{fn_netcdf}_{table}.nc"
        if not os.path.exists(fn_netcdf):
            ds = read_function(fn)
            fn_base = os.path.splitext(os.path.basename(fn))[0]
            ds = ds.expand_dims({"filename": [fn_base]})
            os.makedirs(os.path.dirname(fn_netcdf), exist_ok=True)
            ds.to_netcdf(fn_netcdf)
        return fn_netcdf

    def __call__(
        self,
        read_function: Callable[[str], xr.Dataset],  # function to read a FITS file
    ):
        """Extend the functionality of `read_function` to multiple files.

        The wrapped `read_function` is adapted to take a list of FITS filenames and
        return a `Dataset` which lazily loads data from a cache of netCDF files.
        """

        @wraps(read_function)
        def netcdf_wrapper(fns):
            fns_netcdf = [
                self.single_via_netcdf(read_function, fn) for fn in self.progress(fns)
            ]
            print("Reading netCDF files... ", end="")
            start = time.perf_counter()
            data = xr.open_mfdataset(fns_netcdf, parallel=True)
            dt = time.perf_counter() - start
            print(f"took {dt:.2f} s.")
            return data

        return netcdf_wrapper

# %% ../nbs/01_data.ipynb 6
via_netcdf = ViaNetCDF()

# %% ../nbs/01_data.ipynb 10
def _is_lowres(fn):
    """Check the header of FITS file `fn` to determine if it is low-resolution."""
    return "LR" in fits.getheader(fn)["RES-OBS"]


def get_weave_files(
    level="*",  # pattern to match to the file level, e.g. raw, L1, L2
    filetype="*",  # pattern to match to the file type, e.g. single, stack
    date="*",  # pattern to match to the date in format yyyymmdd
    runid="*",  # pattern to match to the runid
    lowres=True,  # select low-res files, or high-res if False
):
    """Get a list of matching WEAVE files."""
    pattern = f"{level}/{date}/{filetype}_*{runid}*.fits"
    pattern = os.path.join(os.environ["WEAVEIO_ROOTDIR"], pattern)
    files = glob(pattern)
    files.sort()
    if lowres:
        files = [fn for fn in files if _is_lowres(fn)]
    else:
        files = [fn for fn in files if not _is_lowres(fn)]
    return files


def get_lr_l2_stack_files(
    date="*",  # pattern to match to the date in format yyyymmdd
    runid="*",  # pattern to match to the runid
):
    return get_weave_files(
        level="L2", filetype="stack", date=date, runid=runid, lowres=True
    )

# %% ../nbs/01_data.ipynb 21
@via_netcdf
def read_class_table(fn):
    """Read the CLASS_TABLE from a WEAVE L2 FITS file as a Dataset.

    All quantities are indexed by the `APS_ID` of the fibre.
    Chi-square values `CZZ_CHI2_*` for each template are further indexed by redshift `CZZ_*`.
    Coefficients `COEFF` and indexed by integers `I_COEFF`.
    """
    dat = Table.read(fn, "CLASS_TABLE")
    cols = dict(dat)
    cols = {c: cols[c].newbyteorder().byteswap() for c in cols}
    coords = dict(APS_ID=cols.pop("APS_ID"))
    # convert CZZ columns to coordinates
    for c in list(cols):
        if c.startswith("CZZ") and "CHI2" not in c:
            czz_all = cols.pop(c)
            czz = czz_all.mean(axis=0).round(3)
            assert (czz == czz_all.round(3)).all()
            coords[c] = czz
    for c in cols:
        dims = ["APS_ID"]
        if c.startswith("CZZ"):
            dims += [c.replace("_CHI2", "")]
        elif c == "COEFF":
            dims += ["I_COEFF"]
        cols[c] = xr.Variable(dims, cols[c], attrs={"unit": str(cols[c].unit)})
    return xr.Dataset(cols, coords)

# %% ../nbs/01_data.ipynb 27
@via_netcdf
def read_star_table(fn):
    """Read the STAR_TABLE from a WEAVE L2 FITS file as a Dataset.

    All quantities are indexed by the `APS_ID` of the fibre.
    The covariance matrix `COVAR` is additionally indexed by `I_COVAR`, `J_COVAR`.
    The elements `ELEM` and `ELEM_ERR` are additionally indexed by `I_ELEM`.
    """
    dat = Table.read(fn, "STAR_TABLE")
    cols = dict(dat)
    cols = {c: cols[c].newbyteorder().byteswap() for c in cols}
    coords = dict(APS_ID=cols.pop("APS_ID"))
    coords["I_COVAR"] = coords["J_COVAR"] = ["TEFF", "LOGG", "FEH", "ALPHA", "MICRO"]
    for c in cols:
        dims = ["APS_ID"]
        if c == "COVAR":
            dims += ["I_COVAR", "J_COVAR"]
        elif "ELEM" in c:
            dims += ["I_ELEM"]
        cols[c] = xr.Variable(dims, cols[c], attrs={"unit": str(cols[c].unit)})
    return xr.Dataset(cols, coords)

# %% ../nbs/01_data.ipynb 32
def not_line_col(c):
    """Identify columns that do not contain line measurements."""
    c = c.replace("ERR_", "")
    for n in ["EBMV", "FLUX", "AMPL", "Z", "SIGMA", "AON", "FWHM"]:
        if c.startswith(n + "_"):
            return False
    return True


@via_netcdf
def read_galaxy_table(fn):
    """Read the GALAXY_TABLE from a WEAVE L2 FITS file as a Dataset.

    All quantities are indexed by the `APS_ID` of the fibre.
    The `*EBMV*` have two elements additionally indexed by `I_EBMV`.
    """
    # TODO: add units where missing
    dat = Table.read(fn, "GALAXY_TABLE", unit_parse_strict="silent")
    cols = dict(dat)
    cols = {c: cols[c].newbyteorder().byteswap() for c in cols}
    coords = dict(APS_ID=cols.pop("APS_ID"))
    out_cols = {}
    for i, c in enumerate(cols):
        dims = ["APS_ID"]
        if "EBMV" in c:
            dims += ["I_EBMV"]
        if i > 100 and not_line_col(c):
            out_c = f"IDX_{c}"
        else:
            out_c = c
        out_cols[out_c] = xr.Variable(dims, cols[c], attrs={"unit": str(cols[c].unit)})
    return xr.Dataset(out_cols, coords)

# %% ../nbs/01_data.ipynb 37
@via_netcdf
def read_class_spec(fn):
    """Read the CLASS_SPEC from a WEAVE L2 FITS file as a Dataset.

    All quantities are indexed by the `APS_ID` of the fibre.
    Spectral quantities are additionally indexed by wavelength `LAMBDA_{B,R}`.
    """
    dat = Table.read(fn, "CLASS_SPEC")
    cols = dict(dat)
    cols = {c: cols[c].newbyteorder().byteswap() for c in cols}
    coords = dict(APS_ID=cols.pop("APS_ID"))
    for c in list(cols):
        if c.startswith("LAMBDA"):
            band = c.split("_")[-1]
            wl_all = cols.pop(c)
            wl = wl_all.mean(axis=0).round(3)
            assert (wl == wl_all.round(3)).all()
            coords[f"LAMBDA_{band}"] = wl
    for c in cols:
        dims = ["APS_ID"]
        if c.endswith("_B"):
            dims += ["LAMBDA_B"]
        elif c.endswith("_R"):
            dims += ["LAMBDA_R"]
        cols[c] = xr.Variable(dims, cols[c], attrs={"unit": str(cols[c].unit)})
    return xr.Dataset(cols, coords)

# %% ../nbs/01_data.ipynb 42
@via_netcdf
def read_star_spec(fn):
    """Read the STAR_SPEC from a WEAVE L2 FITS file as a Dataset.

    All quantities are indexed by the `APS_ID` of the fibre.
    Spectral quantities are additionally indexed by wavelength bin `LAMBIN_{R,B,C}`,
    which does *not* correspond to the same wavelength for each spectrum.
    """
    dat = Table.read(fn, "STAR_SPEC")
    cols = dict(dat)
    cols = {c: cols[c].newbyteorder().byteswap() for c in cols}
    coords = dict(APS_ID=cols.pop("APS_ID"))
    for c in cols:
        dims = ["APS_ID"]
        if c.endswith("_B"):
            dims += ["LAMBIN_B"]
        elif c.endswith("_R"):
            dims += ["LAMBIN_R"]
        elif c.endswith("_C"):
            dims += ["LAMBIN_C"]
        cols[c] = xr.Variable(dims, cols[c], attrs={"unit": str(cols[c].unit)})
    return xr.Dataset(cols, coords)

# %% ../nbs/01_data.ipynb 46
@via_netcdf
def read_galaxy_spec(fn):
    """Read the GALAXY_SPEC from a WEAVE L2 FITS file as a Dataset.

    All quantities are indexed by the `APS_ID` of the fibre.
    Spectral quantities are additionally indexed by log-wavelength bin `LOGLAMBIN`,
    which does *not* correspond to the same wavelength for each spectrum.
    """
    dat = Table.read(fn, "GALAXY_SPEC", unit_parse_strict="silent")
    cols = dict(dat)
    cols = {c: cols[c].newbyteorder().byteswap() for c in cols}
    coords = dict(APS_ID=cols.pop("APS_ID"))
    for c in cols:
        dims = ["APS_ID"]
        if c.endswith("_PPXF") or c.endswith("_GAND"):
            dims += ["LOGLAMBIN"]
        cols[c] = xr.Variable(dims, cols[c], attrs={"unit": str(cols[c].unit)})
    return xr.Dataset(cols, coords)
