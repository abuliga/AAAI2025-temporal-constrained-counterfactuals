import logging

from pandas import read_csv,DataFrame
from pm4py import read_xes,format_dataframe,convert_to_event_log
logger = logging.getLogger(__name__)


def import_log_csv(path):
    dataframe = read_csv(path,sep=';')
    dataframe = format_dataframe(dataframe, case_id='Case ID', activity_key='Activity', timestamp_key='time:timestamp')
    event_log = convert_to_event_log(dataframe)
    return event_log




def get_log(filepath):
    """Read in event log from disk
    Uses xes_importer to parse log.
    """
    logger.info("\t\tReading in log from {}".format(filepath))
    # uses the xes, or csv importer depending on file type
    if filepath.endswith('.csv'):
        event_log = import_log_csv(filepath)
    elif filepath.endswith('.xes'):
        event_log = read_xes(filepath)
    if isinstance(event_log,DataFrame):
        event_log = convert_to_event_log(event_log)
    return event_log
