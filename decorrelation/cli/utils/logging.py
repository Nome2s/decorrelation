# AUTOGENERATED! DO NOT EDIT! File to edit: ../../../nbs/CLI/utils/logging.ipynb.

# %% auto 0
__all__ = ['get_logger', 'log_args', 'zarr_info', 'darr_info']

# %% ../../../nbs/CLI/utils/logging.ipynb 3
import logging
import sys
import random
import string
import inspect
from functools import wraps

import zarr
from dask import array as da

# %% ../../../nbs/CLI/utils/logging.ipynb 4
def _get_random_string(length=36):
    # choose from all lowercase letter
    letters = string.ascii_lowercase
    result_str = ''.join(random.choice(letters) for i in range(length))
    return result_str

# %% ../../../nbs/CLI/utils/logging.ipynb 5
def get_logger(name:str=None, # name of the application, optional. default: the function name that call this function
               logfile:str=None, # logfile, optional. default: no logfile
               level:str=None, # log level, debug or info, optional. default: info
              ):
    '''get logger for decorrelation cli application'''

    if not name:
        name = inspect.stack()[1][3] #obtain the previous level function name
    
    if not level:
        level = 'info'
    if level == 'info':
        level = logging.INFO
    elif level == 'debug':
        level = logging.DEBUG
    else:
        raise NotImplementedError('only debug and info level are supported')

    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    DATE_FORMAT = "%m/%d/%Y %H:%M:%S %p"
    random_logger_name = _get_random_string(36)
    #The real name of the logger is set to random string to prevent events propogating.

    logger = logging.getLogger(random_logger_name)
    logger.setLevel(level)
    formatter = logging.Formatter(f'%(asctime)s - {name} - %(levelname)s - %(message)s',datefmt='%Y-%m-%d %H:%M:%S')

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

# %% ../../../nbs/CLI/utils/logging.ipynb 6
def log_args(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        ba = inspect.signature(func).bind(*args, **kwargs)
        ba.apply_defaults()
        func_args = ba.arguments
        logger = get_logger(func.__name__,logfile=func_args['log'])
        func_args_strs = map("{0[0]} = {0[1]!r}".format, func_args.items())
        logger.info('fetching args:')
        for item in func_args_strs:
            logger.info(item)
        logger.info('fetching args done.')
        return func(*args, **kwargs)
    return wrapper

# %% ../../../nbs/CLI/utils/logging.ipynb 7
def zarr_info(path, # string to zarr
              zarr, # zarr dataset
              logger, # logger
             ):
    logger.info(f'{path} zarray shape: '+str(zarr.shape))
    logger.info(f'{path} zarray chunks: '+str(zarr.chunks))
    logger.info(f'{path} zarray dtype: '+str(zarr.dtype))

# %% ../../../nbs/CLI/utils/logging.ipynb 8
def darr_info(name, # printing name of the dask array
              darr, # dask array
              logger, # logger
             ):
    logger.info(f'{name} dask array shape: '+str(darr.shape))
    logger.info(f'{name} dask array chunks: '+str(darr.chunks))
    logger.info(f'{name} dask array dtype: '+str(darr.dtype))
