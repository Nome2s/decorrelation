# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/CLI/logging.ipynb.

# %% auto 0
__all__ = ['McLogger', 'mc_logger', 'get_logger']

# %% ../../nbs/CLI/logging.ipynb 3
import logging
import sys
import random
import string
import inspect
from functools import wraps
import types

import zarr
from dask import array as da

# %% ../../nbs/CLI/logging.ipynb 4
class McLogger(logging.getLoggerClass()):
    def zarr_info(self, # logger
                  path, # string to zarr
                  zarr, # zarr dataset
                 ):
        self.info(f'{path} zarray shape: '+str(zarr.shape))
        self.info(f'{path} zarray chunks: '+str(zarr.chunks))
        self.info(f'{path} zarray dtype: '+str(zarr.dtype))
    
    def darr_info(self, # logger
                  name, # printing name of the dask array
                  darr, # dask array
                 ):
        self.info(f'{name} dask array shape: '+str(darr.shape))
        self.info(f'{name} dask array chunksize: '+str(darr.chunksize))
        self.info(f'{name} dask array dtype: '+str(darr.dtype))

# %% ../../nbs/CLI/logging.ipynb 5
def mc_logger(func):
    @wraps(func)
    def log_args(*args, **kwargs):
        logging.setLoggerClass(McLogger)
        logger = logging.getLogger(__name__)
        logger.info(f'running function: {func.__name__}')
        ba = inspect.signature(func).bind(*args, **kwargs)
        ba.apply_defaults()
        func_args = ba.arguments
        func_args_strs = map("{0[0]} = {0[1]!r}".format, func_args.items())
        logger.info('fetching args:')
        for item in func_args_strs:
            logger.info(item)
        logger.info('fetching args done.')
        return func(*args, **kwargs)
    return log_args

# %% ../../nbs/CLI/logging.ipynb 6
def get_logger(logfile:str=None, # logfile, optional. default: no logfile
              ):
    '''get logger for decorrelation cli application'''
    
    level = logging.INFO
    logger = logging.getLogger()
    # print(logger.zarr_info)
    logger.setLevel(level)
    formatter = logging.Formatter(f'%(asctime)s - %(funcName)s - %(levelname)s - %(message)s',datefmt='%Y-%m-%d %H:%M:%S')

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    if logfile:
        file_handler = logging.FileHandler(logfile)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger