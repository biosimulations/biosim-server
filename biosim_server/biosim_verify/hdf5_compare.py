import copy
from functools import partial
from pathlib import Path
from zipfile import ZipFile

import h5py  # type: ignore
import numpy as np
from h5py import HLObject
from numpy.typing import NDArray


def _get_ds_dictionaries(ds_dict: dict[str, NDArray[np.float64]], _name: str, node: HLObject) -> None:
    # From https://stackoverflow.com/questions/70055365/hdf5-file-to-dictionary
    fullname = node.name
    if isinstance(node, h5py.Dataset):
        # node is a dataset
        # print(f"Dataset: {fullname}; adding to dictionary")
        ds_dict[fullname] = np.array(node)
        # print('ds_dict size', len(ds_dict))
    # else:
        # node is a group
        # print(f'Group: {fullname}; skipping')


def get_results(results_zip_file: Path) -> dict[str, dict[str, NDArray[np.float64]]]:
    results: dict[str, dict[str, NDArray[np.float64]]] = {}
    with ZipFile(results_zip_file, "r") as the_zip:
        for name in the_zip.namelist():
            if "reports.h5" in name:
                with h5py.File(the_zip.open(name)) as h5:
                    ds_dict: dict[str, NDArray[np.float64]] = {}
                    ds_visitor = partial(_get_ds_dictionaries, ds_dict)
                    h5.visititems(ds_visitor)
                    results[name] = copy.deepcopy(ds_dict)
    return results


def compare_arrays(arr1: NDArray[np.float64], arr2: NDArray[np.float64],
                   rtol: float = 1e-4, atol_min: float = 1e-3, atol_scale: float = 1e-5) -> tuple[bool, float]:
    # np.seterr(divide='raise')
    if isinstance(arr1[0], np.float64):
        if np.isnan(arr1).any() or np.isnan(arr2).any():
            return False, 1e10
        max1 = np.nanmax(arr1)
        max2 = np.nanmax(arr2)
        atol = np.nanmax([atol_min, max1*atol_scale, max2*atol_scale])
        try:
            score = np.nanmax(abs(arr1 - arr2) / (atol + rtol * abs(arr2)))
        except FloatingPointError as e:
            print(e)
            score = 1e12
        close = np.allclose(arr1, arr2, rtol=rtol, atol=atol, equal_nan=False)
        assert(score <= 1) == close
        return close, score
    # absolute(a - b) <= (atol + rtol * absolute(b))
    maxscore = 0.0
    allclose = True
    for n in range(len(arr1)):
        close, score = compare_arrays(arr1[n], arr2[n])
        maxscore = max(maxscore, score)
        allclose = allclose and close
    return allclose, maxscore


def compare_datasets(results1: dict[str, dict[str, NDArray[np.float64]]],
                     results2: dict[str, dict[str, NDArray[np.float64]]]) -> tuple[bool, float]:
    maxscore = 0.0
    allclose = True
    for h5_file_path in results1:
        if h5_file_path not in results2:
            return False, 1e10
        for dataset_name in results1[h5_file_path]:
            if dataset_name not in results2[h5_file_path]:
                return False, 1e10
            arr1 = results1[h5_file_path][dataset_name]
            arr2 = results2[h5_file_path][dataset_name]
            if arr1.shape != arr2.shape:
                return False, 1e10
            close, score = compare_arrays(arr1, arr2)
            maxscore = max(maxscore, score)
            allclose = allclose and close
    return allclose, maxscore
