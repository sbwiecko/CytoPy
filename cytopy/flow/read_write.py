from multiprocessing import Pool, cpu_count
from ..data.utilities import filter_fcs_files
import flowio
import dateutil.parser as date_parser
import numpy as np
import pandas as pd
import json


def chunks(df_list: list, n: int) -> pd.DataFrame:
    """
    Yield successive n-sized chunks from l.
    ref: https://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks
    :param df_list: list of dataframes to generated 'chunks' from
    :param n: number of chunks to generate
    :return: Yields successive n-sized DataFrames
    """
    for i in range(0, len(df_list), n):
        yield df_list[i:i + n]


def fcs_mappings(path: str) -> list or None:
    """
    Fetch channel mappings from fcs file.
    :param path: path to fcs file
    :return: List of channel mappings. Will return None if file fails to load.
    """
    try:
        fo = FCSFile(path)
    except ValueError as e:
        print(f'Failed to load file {path}; {e}')
        return None
    return fo.fluoro_mappings


def explore_channel_mappings(fcs_dir: str, exclude_comps: bool = True) -> list:
    """
    Given a directory, explore all fcs files and find all permutations of channel/marker mappings
    :param fcs_dir: root directory to search
    :param exclude_comps: exclude compentation files (must have 'comp' in filename)
    :return: list of all unique channel/marker mappings
    """
    fcs_files = filter_fcs_files(fcs_dir, exclude_comps)
    pool = Pool(cpu_count())
    all_mappings = pool.map(fcs_mappings, fcs_files)
    all_mappings_json = [json.dumps(x) for x in all_mappings]
    unique_mappings = set(all_mappings_json)
    return [json.loads(x) for x in unique_mappings]


class FCSFile:
    """
    Utilising FlowIO to generate an object for representing an FCS file
    Arguments:
        - filepath: location of fcs file to parse
        - comp_matrix: csv file containing compensation matrix (optional, not required if a
        spillover matrix is already linked to the file)
    Attributes:
        filename - embedded filenae
        sys - name of system data acquired on
        total_events - total events measured
        tube_name - name of tube during acquisition
        exp_name - name of experiment during acquisition
        cytometer - name of Cytometer
        creator - name of user that generated fcs file
        fluoro_mappings - list of channel:marker mappings (list of dictionary objects)
        cst_pass - True is CS&T registered as successful on day of acquisition
        data - raw events data
        event_data - numpy array of events data
        dataframe - Pandas DataFrame of events data
        threshold - threshold applied to each channel (list of dictionary {channel : threshold})
        processing date - date data was acquired
        spill - Pandas DataFrame corresponding to spillover matrix
    Methods:
        compensate - using embedded spillover matrix or provided spillover matrix, compensate the data
    """
    def __init__(self, filepath, comp_matrix=None):
        fcs = flowio.FlowData(filepath)
        self.filename = fcs.text.get('fil', 'Unknown_filename')
        self.sys = fcs.text.get('sys', 'Unknown_system')
        self.total_events = int(fcs.text.get('tot', 0))
        self.tube_name = fcs.text.get('tube name', 'Unknown')
        self.exp_name = fcs.text.get('experiment name', 'Unknown')
        self.cytometer = fcs.text.get('cyt', 'Unknown')
        self.creator = fcs.text.get('creator', 'Unknown')
        self.operator = fcs.text.get('export user name', 'Unknown')
        self.fluoro_mappings = self._get_fluoro_mapping(fcs.channels)
        self.cst_pass = False
        self.data = fcs.events
        self.event_data = np.reshape(np.array(fcs.events, dtype=np.float32), (-1, fcs.channel_count))
        if 'threshold' in fcs.text.keys():
            self.threshold = [{'channel': c, 'threshold': v} for c, v in chunks(fcs.text["threshold"].split(','), 2)]
        else:
            self.threshold = 'Unknown'
        try:
            self.processing_date = date_parser.parse(fcs.text['date'] +
                                                     ' ' + fcs.text['etim']).isoformat()
        except KeyError:
            self.processing_date = 'Unknown'
        if comp_matrix is not None:
            self.spill = pd.read_csv(comp_matrix)
        else:
            try:
                assert 'spill' in fcs.text.keys()
                if(len(fcs.text['spill'])) < 1:
                    raise KeyError("""Error: no spillover matrix found, please provide
                    path to relevant csv file with 'comp_matrix' argument""")
                self.spill = self._get_spill_matrix(fcs.text['spill'])
            except AssertionError:
                self.spill = None
        if 'cst_setup_status' in fcs.text:
            if fcs.text['cst setup status'] == 'SUCCESS':
                self.cst_pass = True

    @property
    def dataframe(self):
        columns = [f"{x['channel']}_{x['marker']}" for x in self.fluoro_mappings]
        return pd.DataFrame(self.event_data, columns=columns)

    @staticmethod
    def _get_fluoro_mapping(fluoro_dict: dict) -> list:
        """
        Generates a list of dictionary objects that describe the fluorochrome mappings in this FCS file
        :param fluoro_dict: dictionary object from the channels param of the fcs file
        :return: array of dict obj with keys 'channel' and 'marker'. Use to map fluorochrome channels to
        corresponding marker
        """
        fm = [x for k, x in fluoro_dict.items()]
        mappings = []
        for fm_ in fm:
            channel = fm_['PnN'].replace('_', '-')
            if 'PnS' in fm_.keys():
                marker = fm_['PnS'].replace('_', '-')
            else:
                marker = ''
            mappings.append({'channel': channel, 'marker': marker})
        return mappings

    @staticmethod
    def _get_spill_matrix(matrix_string: str) -> pd.DataFrame:
        """
        Generate pandas dataframe for the fluorochrome spillover matrix used for compensation calc
        :param matrix_string: string value extracted from the 'spill' parameter of the FCS file
        :return: numpy matrix

        Code is modified from: https://github.com/whitews/FlowUtils
        Pedersen NW, Chandran PA, Qian Y, et al. Automated Analysis of Flow Cytometry
        Data to Reduce Inter-Lab Variation in the Detection of Major Histocompatibility
        Complex Multimer-Binding T Cells. Front Immunol. 2017;8:858.
        Published 2017 Jul 26. doi:10.3389/fimmu.2017.00858
        """
        matrix_list = matrix_string.split(',')
        n = int(matrix_list[0])
        header = matrix_list[1:(n+1)]
        header = [i.strip().replace('\n', '') for i in header]
        values = [i.strip().replace('\n', '') for i in matrix_list[n+1:]]
        matrix = np.reshape(list(map(float, values)), (n, n))
        matrix_df = pd.DataFrame(matrix)
        matrix_df = matrix_df.rename(index={k: v for k, v in zip(matrix_df.columns.to_list(), header)},
                                     columns={k: v for k, v in zip(matrix_df.columns.to_list(), header)})
        return matrix_df

    def compensate(self):
        """
        Apply compensation to event data
        :return: None
        """
        # Remove FSC, SSC, and Time data for compensation
        assert self.spill is not None, f'Unable to locate spillover matrix, please provide a compensation matrix'
        channels = [x['channel'] for x in self.fluoro_mappings]
        channel_idx = [i for i, x in enumerate(channels) if not any([x.find(s) != -1 for
                                                                     s in ['FSC', 'SSC', 'Time', 'FS', 'SS']])]
        comp_data = self.event_data[:, channel_idx]
        comp_data = np.linalg.solve(self.spill.values.T, comp_data.T).T
        self.event_data[:, channel_idx] = comp_data

