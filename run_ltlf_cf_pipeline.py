import logging
import time
import warnings
import os
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from src.encoding.common import get_encoded_df, EncodingType
from src.encoding.constants import TaskGenerationType, PrefixLengthStrategy, EncodingTypeAttribute
from src.encoding.time_encoding import TimeEncodingType
from src.evaluation.common import evaluate_classifier
from src.explanation.common import ExplainerType, explain
from src.hyperparameter_optimisation.common import retrieve_best_model, HyperoptTarget
from src.labeling.common import LabelTypes
from src.log.common import get_log
from src.predictive_model.common import ClassificationMethods, get_tensor
from src.predictive_model.predictive_model import PredictiveModel, drop_columns

import random
from dataset_confs import DatasetConfs
from Declare4Py.Utils.utils import *
from logaut import ltl2dfa
from flloat.parser.ltlf import LTLfParser
from Declare4Py.D4PyEventLog import D4PyEventLog
from Declare4Py.ProcessModels.LTLModel import LTLModel, LTLTemplate
from Declare4Py.ProcessMiningTasks.ConformanceChecking.LTLAnalyzer import LTLAnalyzer
import re
from Declare4Py.D4PyEventLog import D4PyEventLog
import os
from pm4py import convert_to_event_log, format_dataframe

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning)


def dict_mean(dict_list):
    mean_dict = {}
    for key in dict_list[0].keys():
        mean_dict[key] = sum(d[key] for d in dict_list) / len(dict_list)
    return mean_dict


def run_simple_pipeline(CONF=None, dataset_name=None):
    random.seed(CONF['seed'])
    np.random.seed(CONF['seed'])
    dataset_confs = DatasetConfs(dataset_name=dataset_name, where_is_the_file=CONF['data'])

    logger.debug('LOAD DATA')
    log = get_log(filepath=CONF['data'])

    if 'bpic2012' or 'synthetic_data' in dataset_name:
        for trace in log:
            for event in trace:
                event['concept:name'] = (event['concept:name'].replace('_', '').replace('-', '').replace(' ', '').replace('(','')
                                         .replace(')','').lower())
    logger.debug('ENCODE DATA')
    encoder, full_df = get_encoded_df(log=log, CONF=CONF)
    logger.debug('TRAIN PREDICTIVE MODEL')
    train_size = CONF['train_val_test_split'][0]
    val_size = CONF['train_val_test_split'][1]
    test_size = CONF['train_val_test_split'][2]
    if train_size + val_size + test_size != 1.0:
        raise Exception('Train-val-test split does not sum up to 1')
    train_df,val_df,test_df = np.split(full_df,[int(train_size*len(full_df)), int((train_size+val_size)*len(full_df))])

    predictive_model = PredictiveModel(CONF, CONF['predictive_model'], train_df, val_df)
    predictive_model.model, predictive_model.config = retrieve_best_model(
        predictive_model,
        CONF['predictive_model'],
        max_evaluations=CONF['hyperparameter_optimisation_epochs'],
        target=CONF['hyperparameter_optimisation_target'],
        seed=CONF['seed']
    )

    logger.debug('EVALUATE PREDICTIVE MODEL')
    if predictive_model.model_type is ClassificationMethods.LSTM.value:
        probabilities = predictive_model.model.predict(get_tensor(CONF, drop_columns(test_df)))
        predicted = np.argmax(probabilities, axis=1)
        scores = np.amax(probabilities, axis=1)
    elif predictive_model.model_type not in (ClassificationMethods.LSTM.value):
        predicted = predictive_model.model.predict(drop_columns(test_df))
        scores = predictive_model.model.predict_proba(drop_columns(test_df))[:, 1]

    actual = test_df['label']
    if predictive_model.model_type is ClassificationMethods.LSTM.value:
        actual = np.array(actual.to_list())
    def extract_matching_substrings(input_string, alphabet):
        pattern = '|'.join(re.escape(sub) for sub in alphabet)

        # Find all occurrences of the pattern in the input string
        matches = re.findall(pattern, input_string)

        return matches

    # Example usage
    def extract_names(text):
        # Use regular expression to find text within parentheses
        pattern = r'\((.*?)\)'
        matches = re.findall(pattern, text)

        # Remove spaces and letters from each match
        cleaned_names = [re.sub(r'[^a-zA-Z]', '', match).lower().strip('f').strip('g').strip('u') for match in matches]

        return cleaned_names
    event_log = D4PyEventLog(case_name="case:concept:name")
    population_df = full_df.copy()
    encoder.decode(population_df)
    long_data = pd.wide_to_long(population_df.drop_duplicates(subset=['trace_id']), stubnames=['prefix'],
                                i='trace_id',
                                j='order', sep='_', suffix=r'\w+')
    timestamps = pd.date_range('1/1/2011', periods=len(long_data), freq='H')
    long_data_sorted = long_data.sort_values(['trace_id', 'order'], ).reset_index(drop=False)
    long_data_sorted['time:timestamp'] = timestamps
    long_data_sorted.drop(columns=['order'], inplace=True)
    columns_to_rename = {'trace_id': 'case:concept:name', 'prefix': 'concept:name'}
    long_data_sorted.rename(columns=columns_to_rename, inplace=True)
    long_data_sorted['label'].replace({'regular': 'false', 'deviant': 'true'}, inplace=True)
    long_data_sorted.replace('0', 'other', inplace=True)
    dataframe = format_dataframe(long_data_sorted, case_id='case:concept:name', activity_key='concept:name',
                                 timestamp_key='time:timestamp')
    log = convert_to_event_log(dataframe)

    event_log.load_xes_log(log)
    ltlf_model = LTLModel(backend='ltlf2dfa')
    #Below are the LTLf models for the different datasets
    if 'bpic2012' in dataset_name:
        model_strings = {
            '10%':'F(osentcomplete) & G(osentcomplete ->(!(aacceptedcomplete)U(wcompleterenaanvraagcomplete))) & F(osentbackcomplete)',
            '25%':' F(osentcomplete) & G(osentcomplete ->(!(aacceptedcomplete)U(wcompleterenaanvraagcomplete))) &F(osentbackcomplete) &  G(wcompleterenaanvraagstart -> F(aacceptedcomplete)) & (F(wnabellenoffertesstart) & F(wnabellenoffertescomplete)) &  (F(oselectedcomplete) |F(wvaliderenaanvraagstart))',
             '50%': 'F(osentcomplete) & G(osentcomplete ->(!(aacceptedcomplete)U(wcompleterenaanvraagcomplete))) & G(wcompleterenaanvraagschedule->F(wcompleterenaanvraagstart)) & (F(wnabellenoffertesstart) | F(wnabellenoffertescomplete)) & (F(oselectedcomplete) | F(wvaliderenaanvraagstart)) &  \
                                         asubmittedcomplete & F(oselectedcomplete | apartlysubmittedcomplete) & G(ocreatedcomplete -> F(osentbackcomplete)) & F(afinalizedcomplete) | F(apreacceptedcomplete) | F(wafhandelenleadscomplete))',
                               }
    elif 'BPIC17' in dataset_name:
        model_strings = {'10%':'acreateapplication & (!(aconcept)U(wcompleteapplication))',
                         '25%':'acreateapplication & (!(aconcept)U(wcompleteapplication)) & (F(ocreateoffer) -> F(wcallafteroffers)) & F(wcompleteapplication)',
                         '50%':'acreateapplication & (!(aconcept)U(wcompleteapplication)) & (G(ocreateoffer) -> (F(wcallafteroffers) | F(wvalidateapplication))) & (F(ocreated) -> X(osentmailandonline | osentonlineonly)) & G((aincomplete | apending) -> (X(wcallincompletefiles) & F(wvalidateapplication)))' }
    elif 'synthetic_data' in dataset_name:
        model_strings={'10%':'G(contacthospital -> X(acceptclaim | rejectclaim))',
                       '25%':'G(contacthospital -> X(acceptclaim | rejectclaim)) & F(createquestionnaire)',
                        '50%':'(F(contacthospital) -> F(highinsurancecheck)) & G(preparenotificationcontent -> X(sendnotificationbyphone \
                        | sendnotificationbypost)) & G(createquestionnaire-> F(preparenotificationcontent)) & register'
                       }
    for percentage,model_string in model_strings.items():
        #Here we parse the LTLf model
        ltlf_model.parse_from_string(model_string)

        #Here we convert the LTLf model to a DFA
        dfa = ltl2dfa(ltlf_model.parsed_formula, backend='ltlf2dfa')

        analyzer = LTLAnalyzer(event_log, ltlf_model)
        #Here we check the conformance of the traces in the event log with the DFA
        conf_check_res_df = analyzer.run(
            jobs=12,
            minimize_automaton=False, dfa = dfa)
        initial_result = evaluate_classifier(actual, predicted, scores)
        logger.debug('COMPUTE EXPLANATION')

        if CONF['explanator'] is ExplainerType.DICE_LTLf.value:
            # Combine train, validation, and test datasets
            cf_dataset = pd.concat([train_df, val_df], ignore_index=True)
            full_df = pd.concat([train_df, val_df, test_df])
            cf_dataset.loc[len(cf_dataset)] = 0
            model_path = '../experiments/process_models/process_models_new'

            # Filter test dataset for correct predictions with label 0
            test_df_correct = test_df[(test_df['label'] == predicted) & (test_df['label'] == 0)]

            # Define the different configurations
            configurations = [
                #This is the baseline genetic_\varphi
                {'setup': {'genetic_ltlf': ['baseline']}, 'heuristics': ['heuristic_1'], 'adapted': False},
                #In order, we have the heuristic_1, corresponding to the APRIORI strategy, heuristic_2, corresponding to the ONLINE strategy,
                # and the Mutate and Retry baseline
                {'setup': {'genetic_ltlf': ['baseline']}, 'heuristics': ['heuristic_1', 'heuristic_2', 'mar'],
                 'adapted': True}
            ]
            encoder.decode(full_df)

            # Normalize and encode the model string
            model_strings = extract_names(Utils.normalize_formula(model_string))
            encoder.encode(full_df)
            for config in configurations:
                setup = config['setup']
                heuristics = config['heuristics']
                adapted = config['adapted']

                for method, optimizations in setup.items():
                    for heuristic in heuristics:
                        for optimization in optimizations:
                            print(
                                f"Running method: {method}, optimization: {optimization}, heuristic: {heuristic}, adapted: {adapted}")


                            # Filter the full dataset and test dataset based on conformance check results
                            accepted_cases = conf_check_res_df[conf_check_res_df['accepted'] == True][
                                'case:concept:name']
                            full_df = full_df[full_df['trace_id'].isin(accepted_cases)]
                            test_df_correct = test_df_correct[test_df_correct['trace_id'].isin(accepted_cases)]

                            # Set the path for results
                            path_results = os.path.join('results')

                            # Call the explain function with the current configuration
                            explain(
                                CONF,
                                predictive_model,
                                encoder=encoder,
                                query_instances=test_df_correct.iloc[:, 1:],
                                method=method,
                                df=full_df.iloc[:, 1:],
                                optimization=optimization,
                                heuristic=heuristic,
                                model_path=model_path,
                                random_seed=CONF['seed'],
                                adapted=adapted,
                                ltlf_model=ltlf_model,
                                model_names=model_strings,
                                percentage=percentage,
                                path_results=path_results,
                                dfa=dfa
                            )

    logger.info('RESULT')
    logger.info('INITIAL', initial_result)
    logger.info('Done, cheers!')

if __name__ == '__main__':
    dataset_list = {
        'synthetic_data' : [7,9,11,13],
       'bpic2012_O_ACCEPTED-COMPLETE':[20,25,30,35],
    'BPIC17_O_ACCEPTED':[15,20,25,30],
    }
    #The dataset_list contains the datasets and the prefix lengths reported in the paper, used for the experiments
    for dataset,prefix_lengths in dataset_list.items():
        for prefix in prefix_lengths:
                CONF = {  # This contains the configuration for the run
                    'data': os.path.join(dataset, 'full.xes'),
                    'train_val_test_split': [0.7, 0.15, 0.15],
                    'output': os.path.join('..', 'output_data'),
                    'prefix_length_strategy': PrefixLengthStrategy.FIXED.value,
                    'prefix_length': prefix,
                    'padding': True,  # TODO, why use of padding?
                    'feature_selection': EncodingType.SIMPLE.value,
                    'task_generation_type': TaskGenerationType.ONLY_THIS.value,
                    'attribute_encoding': EncodingTypeAttribute.LABEL.value,  # LABEL, ONEHOT
                    'labeling_type': LabelTypes.ATTRIBUTE_STRING.value,
                    'predictive_model': ClassificationMethods.XGBOOST.value,  # RANDOM_FOREST, LSTM, PERCEPTRON
                    'explanator': ExplainerType.DICE_LTLf.value,  # SHAP, LRP, ICE, DICE
                    'threshold': 13,
                    'top_k': 10,
                    'hyperparameter_optimisation': False,  # TODO, this parameter is not used
                    'hyperparameter_optimisation_target': HyperoptTarget.AUC.value,
                    'hyperparameter_optimisation_epochs': 20,
                    'time_encoding': TimeEncodingType.NONE.value,
                    'target_event': None,
                    'seed': 42,
                }
                run_simple_pipeline(CONF=CONF, dataset_name=dataset)
