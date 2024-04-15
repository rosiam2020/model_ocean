import datetime
import logging

import extrapolate as ex
import numpy as np

try:
    import ESMF
except:
    try:
        # The module name for ESMPy was changed in v8.4.0 from “ESMF” to “esmpy”
        import esmpy as ESMF
    except ImportError:
        logging.error("[M2R_interp2D] Could not find module ESMF/esmpy")
        pass

__author__ = "Trond Kristiansen"
__email__ = "me@trondkristiansen.com"
__created__ = datetime.datetime(2008, 12, 4)
__modified__ = datetime.datetime(2023, 12, 20)
__version__ = "1.6"
__status__ = "Development"


def laplacefilter(field, threshold, toxi, toeta):
    undef = 2.0e35
    tx = 0.9 * undef
    critx = 0.01
    cor = 1.6
    mxs = 10

    field = np.where(abs(field) > threshold, undef, field)

    field = ex.extrapolate.fill(
        int(1),
        int(toxi),
        int(1),
        int(toeta),
        float(tx),
        float(critx),
        float(cor),
        float(mxs),
        np.asarray(field, order="F"),
        int(toxi),
        int(toeta),
    )
    return field


def do_hor_interpolation_regular_grid(confM2R, mydata, myvar):
    if confM2R.show_progress is True:
        try:
            import progressbar

            widgets = [
                "\rHorizontal interpolation:",
                progressbar.Percentage(),
                progressbar.Bar(),
            ]
            progress = progressbar.ProgressBar(
                confM2R.grdMODEL.nlevels, widgets=widgets
            ).start()
        except ImportError:
            logging.error("[M2R_interp2D] Could not find module progressbar")
            confM2R.show_progress = False
        pass

    index_roms, toxi, toeta, mymask = setup_indexes(confM2R, myvar)
    array1 = np.zeros(index_roms, dtype=float)

    # 2D or 3D interpolation
    depth_levels = confM2R.grdMODEL.nlevels

    if myvar in ["ssh", "ageice", "uice", "vice", "aice", "hice", "snow_thick", "hs"]:
        depth_levels = 1

    for k in range(depth_levels):
        if depth_levels == 1:
            indata = np.squeeze(mydata[:, :])
        else:
            indata = np.squeeze(mydata[k, :, :])

        # We interpolate to RHO fields for all variables and then we later interpolate RHO points to U and V points
        # But input data are read on U and V and RHO grids if they differ (as NorESM and GLORYS does).
        if myvar in ["uice"]:
            confM2R.grdMODEL.fieldSrc_rho.data[:, :] = np.flipud(np.rot90(indata))
            field = confM2R.grdROMS.regridSrc2Dst_u(
                confM2R.grdMODEL.fieldSrc_rho, confM2R.grdROMS.fieldDst_u
            )
        elif myvar in ["vice"]:
            confM2R.grdMODEL.fieldSrc_rho.data[:, :] = np.flipud(np.rot90(indata))
            field = confM2R.grdROMS.regridSrc2Dst_v(
                confM2R.grdMODEL.fieldSrc_rho, confM2R.grdROMS.fieldDst_v
            )
        else:
            confM2R.grdMODEL.fieldSrc_rho.data[:, :] = np.flipud(np.rot90(indata))
            field = confM2R.grdROMS.regridSrc2Dst_rho(
                confM2R.grdMODEL.fieldSrc_rho, confM2R.grdROMS.fieldDst_rho
            )

        # Since ESMF uses coordinates (x,y) we need to rotate and flip to get back to (y,x) order.
        field = np.fliplr(np.rot90(field.data, 3))

        if confM2R.use_filter and myvar not in ["aice", "hice", "ageice"]:
            field = laplacefilter(field, 1000, toxi, toeta)
            field = field * mymask

        array1[k, :, :] = field

        if k in [2, 0] and False is True:
            import matplotlib.pyplot as plt

            import plotData

            plotData.contourMap(
                confM2R.grdROMS,
                confM2R.grdROMS.lon_rho,
                confM2R.grdROMS.lat_rho,
                field,
                str(k) + "_withfilter",
                myvar,
            )
            plotfilename = "test_{}_wfilter.png".format(myvar)
            plt.savefig(plotfilename, dpi=150)

        if confM2R.show_progress is True:
            progress.update(k)
    if confM2R.show_progress is True:
        progress.finish()
    return array1


def setup_indexes(confM2R, myvar):
    if myvar in ["uice"]:
        indexROMS_Z_ST = (
            confM2R.grdMODEL.nlevels,
            confM2R.grdROMS.eta_u,
            confM2R.grdROMS.xi_u,
        )
        toxi = confM2R.grdROMS.xi_u
        toeta = confM2R.grdROMS.eta_u
        mymask = confM2R.grdROMS.mask_u

    elif myvar in ["vice"]:
        indexROMS_Z_ST = (
            confM2R.grdMODEL.nlevels,
            confM2R.grdROMS.eta_v,
            confM2R.grdROMS.xi_v,
        )
        toxi = confM2R.grdROMS.xi_v
        toeta = confM2R.grdROMS.eta_v
        mymask = confM2R.grdROMS.mask_v

    else:
        indexROMS_Z_ST = (
            confM2R.grdMODEL.nlevels,
            confM2R.grdROMS.eta_rho,
            confM2R.grdROMS.xi_rho,
        )
        toxi = confM2R.grdROMS.xi_rho
        toeta = confM2R.grdROMS.eta_rho
        mymask = confM2R.grdROMS.mask_rho

    return indexROMS_Z_ST, toxi, toeta, mymask


def setup_ESMF_interpolation_weights(confM2R):
    logging.info(
        "[M2R_interp2D] ==> Creating the interpolation weights and indexes using ESMF (this may take some time....):"
    )
    logging.info("[M2R_interp2D] ==> Source field src at RHO points")

    confM2R.grdMODEL.fieldSrc_rho = ESMF.Field(
        confM2R.grdMODEL.esmfgrid, "fieldSrc", staggerloc=ESMF.StaggerLoc.CENTER
    )

    logging.info("[M2R_interp2D] ==> Destination field src at RHO, u, and v points")
    confM2R.grdROMS.fieldDst_rho = ESMF.Field(
        confM2R.grdROMS.esmfgrid, "fieldDst", staggerloc=ESMF.StaggerLoc.CENTER
    )

    confM2R.grdROMS.fieldDst_u = ESMF.Field(
        confM2R.grdROMS.esmfgrid_u, "fieldDst", staggerloc=ESMF.StaggerLoc.CENTER
    )

    confM2R.grdROMS.fieldDst_v = ESMF.Field(
        confM2R.grdROMS.esmfgrid_v, "fieldDst", staggerloc=ESMF.StaggerLoc.CENTER
    )

    logging.info("[M2R_interp2D] ==> regridSrc2Dst from RHO to U, V and RHO points")
    confM2R.grdROMS.regridSrc2Dst_rho = ESMF.Regrid(
        confM2R.grdMODEL.fieldSrc_rho,
        confM2R.grdROMS.fieldDst_rho,
        regrid_method=ESMF.RegridMethod.BILINEAR,
        unmapped_action=ESMF.UnmappedAction.IGNORE,
    )

    confM2R.grdROMS.regridSrc2Dst_u = ESMF.Regrid(
        confM2R.grdMODEL.fieldSrc_rho,
        confM2R.grdROMS.fieldDst_u,
        regrid_method=ESMF.RegridMethod.BILINEAR,
        unmapped_action=ESMF.UnmappedAction.IGNORE,
    )

    confM2R.grdROMS.regridSrc2Dst_v = ESMF.Regrid(
        confM2R.grdMODEL.fieldSrc_rho,
        confM2R.grdROMS.fieldDst_v,
        regrid_method=ESMF.RegridMethod.BILINEAR,
        unmapped_action=ESMF.UnmappedAction.IGNORE,
    )
