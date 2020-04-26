# coding: utf-8
__author__ = 'ZFTurbo: https://kaggle.com/zfturbo'


from operator import itemgetter
from gbm_classifiers_regions.a0_read_data import *


SUBM_PATH_DETAILED = SUBM_PATH + 'detailed/'
if not os.path.isdir(SUBM_PATH_DETAILED):
    os.mkdir(SUBM_PATH_DETAILED)


def create_feature_map(features):
    outfile = open('xgb.fmap', 'w')
    for i, feat in enumerate(features):
        outfile.write('{0}\t{1}\tq\n'.format(i, feat))
    outfile.close()


def get_importance(gbm, features):
    create_feature_map(features)
    '''
    ‘weight’ - the number of times a feature is used to split the data across all trees.
    ‘gain’ - the average gain of the feature when it is used in trees
    ‘cover’ - the average coverage of the feature when it is used in trees
    '''
    importance = gbm.get_score(fmap='xgb.fmap', importance_type='weight')
    importance = sorted(importance.items(), key=itemgetter(1), reverse=True)
    return importance


def create_xgboost_model(train, features, params, day):
    import xgboost as xgb
    import matplotlib.pyplot as plt

    print('XGBoost version: {}'.format(xgb.__version__))
    target_name = params['target']
    start_time = time.time()
    if USE_LOG:
        train[target_name] = np.log10(train[target_name] + 1)
    if USE_DIFF:
        if USE_LOG:
            if USE_DIV:
                train[target_name] /= (np.log10(train['case_day_minus_0'] + 1) + 1)
            else:
                train[target_name] -= np.log10(train['case_day_minus_0'] + 1)
        else:
            if USE_DIV:
                train[target_name] /= (train['case_day_minus_0'] + 1)
            else:
                train[target_name] -= (train['case_day_minus_0'] + 1)

    if 0:
        unique_target = np.array(sorted(train[target_name].unique()))
        print('Target length: {}'.format(len(unique_target), unique_target))

    required_iterations = REQUIRED_ITERATIONS
    overall_train_predictions = np.zeros((len(train),), dtype=np.float32)
    overall_importance = dict()

    model_list = []
    for iter1 in range(required_iterations):
        # Looks like we overfit on first day, so set lower params
        if day == 1:
            num_folds = random.choice([4, 5, 6, 7])
            max_depth = random.choice([2, 3, 4])
            eta = random.choice([0.08, 0.1, 0.2])

            subsample = random.choice([0.5, 0.6, 0.7])
            colsample_bytree = random.choice([0.5, 0.6, 0.7])
        else:
            num_folds = random.choice([4, 5, 6, 7])
            max_depth = random.choice([6, 7, 8])
            eta = random.choice([0.02, 0.04, 0.06])

            subsample = random.choice([0.8, 0.9, 0.95, 0.99])
            colsample_bytree = random.choice([0.8, 0.9, 0.95, 0.99])



        eval_metric = random.choice(['rmse'])
        # eval_metric = random.choice(['logloss'])
        ret = get_kfold_split_v2(num_folds, train, 720 + iter1)

        log_str = 'XGBoost iter {}. FOLDS: {} METRIC: {} ETA: {}, MAX_DEPTH: {}, SUBSAMPLE: {}, COLSAMPLE_BY_TREE: {}'.format(iter1,
                                                                                                               num_folds,
                                                                                                               eval_metric,
                                                                                                               eta,
                                                                                                               max_depth,
                                                                                                               subsample,
                                                                                                               colsample_bytree)
        print(log_str)
        params_xgb = {
            "objective": "reg:squarederror",
            # "num_class": 5,
            "booster": "gbtree",
            "eval_metric": eval_metric,
            "eta": eta,
            "max_depth": max_depth,
            "subsample": subsample,
            "colsample_bytree": colsample_bytree,
            "silent": 1,
            "seed": 2017 + iter1,
            "nthread": 6,
            "gamma": 0,
            # 'gpu_id': 0,
            # "tree_method": 'exact',
            "tree_method": 'hist',
            # "tree_method": 'gpu_hist',
            # 'updater': 'grow_gpu',
        }
        if USE_GPU:
            params_xgb['gpu_id'] = 0
            params_xgb['tree_method'] = 'gpu_hist'
            params_xgb['updater'] = 'grow_gpu'
        num_boost_round = 10000
        early_stopping_rounds = 50

        # print('Train shape:', train.shape)
        # print('Features:', features)

        full_single_preds = np.zeros((len(train), ), dtype=np.float32)
        fold_num = 0
        for train_index, valid_index in ret:
            fold_num += 1
            # print('Start fold {}'.format(fold_num))
            X_train = train.loc[train_index].copy()
            X_valid = train.loc[valid_index].copy()
            y_train = X_train[target_name]
            y_valid = X_valid[target_name]

            # print('Train data:', X_train.shape)
            # print('Valid data:', X_valid.shape)

            dtrain = xgb.DMatrix(X_train[features].values, y_train)
            dvalid = xgb.DMatrix(X_valid[features].values, y_valid)

            watchlist = [(dtrain, 'train'), (dvalid, 'eval')]
            gbm = xgb.train(params_xgb, dtrain, num_boost_round, evals=watchlist, early_stopping_rounds=early_stopping_rounds, verbose_eval=False)
            model_list.append(gbm)

            imp = get_importance(gbm, features)
            # print('Importance: {}'.format(imp[:100]))
            for i in imp:
                if i[0] in overall_importance:
                    overall_importance[i[0]] += i[1] / num_folds
                else:
                    overall_importance[i[0]] = i[1] / num_folds

            # print('Best iter: {}'.format(gbm.best_iteration + 1))
            pred = gbm.predict(xgb.DMatrix(X_valid[features].values), ntree_limit=gbm.best_iteration + 1)
            # print(pred.shape)
            full_single_preds[valid_index] += pred.copy()

            pred = gbm.predict(dvalid, ntree_limit=gbm.best_iteration + 1)
            try:
                score = contest_metric(y_valid, pred)
                # print('Fold {} score: {:.6f}'.format(fold_num, score))
            except Exception as e:
                print('Error:', e)

        # print(len(train[target_name].values), len(full_single_preds))

        train_tmp = train.copy()
        train_tmp['pred'] = full_single_preds
        train_tmp = decrease_table_for_last_date(train_tmp)

        score = contest_metric(train_tmp[target_name].values, train_tmp['pred'].values)
        overall_train_predictions += full_single_preds
        print('Score iter {}: {:.6f} Time: {:.2f} sec'.format(iter1, score, time.time() - start_time))

    overall_train_predictions /= required_iterations
    for el in overall_importance:
        overall_importance[el] /= required_iterations
    imp = sort_dict_by_values(overall_importance)
    names = []
    values = []
    print('Total importance count: {}'.format(len(imp)))
    output_features = 100
    for i in range(min(output_features, len(imp))):
        print('{}: {:.6f}'.format(imp[i][0], imp[i][1]))
        names.append(imp[i][0])
        values.append(imp[i][1])

    if 0:
        fig, ax = plt.subplots(figsize=(10, 25))
        ax.barh(list(range(min(output_features, len(imp)))), values, 0.4, color='green', align='center')
        ax.set_yticks(list(range(min(output_features, len(imp)))))
        ax.set_yticklabels(names)
        ax.invert_yaxis()
        plt.subplots_adjust(left=0.47)
        plt.savefig('debug.png')

    if USE_DIFF:
        if USE_LOG:
            if USE_DIV:
                train[target_name] *= (np.log10(train['case_day_minus_0'] + 1) + 1)
                overall_train_predictions *= (np.log10(train['case_day_minus_0'] + 1) + 1)
            else:
                train[target_name] += np.log10(train['case_day_minus_0'] + 1)
                overall_train_predictions += np.log10(train['case_day_minus_0'] + 1)
        else:
            if USE_DIV:
                train[target_name] *= (train['case_day_minus_0'] + 1)
                overall_train_predictions *= (train['case_day_minus_0'] + 1)
            else:
                train[target_name] += (train['case_day_minus_0'] + 1)
                overall_train_predictions += (train['case_day_minus_0'] + 1)

    if USE_LOG:
        train[target_name] = np.power(10, train[target_name]) - 1
        overall_train_predictions = np.power(10, overall_train_predictions) - 1

    neg_val = (overall_train_predictions < 0).astype(np.int32).sum()
    print('Negative values: {}'.format(neg_val))

    overall_train_predictions[overall_train_predictions < 0] = 0
    train_tmp = train.copy()
    train_tmp['pred'] = overall_train_predictions

    # We now that value must be equal or higher
    count_less = (train_tmp['pred'] < train_tmp['case_day_minus_0']).astype(np.int32).sum()
    if count_less > 0:
        print('Values less than needed: {} ({:.4f} %)'.format(count_less, 100*count_less / len(train_tmp)))
    train_tmp['pred'] = np.maximum(train_tmp['pred'], train_tmp['case_day_minus_0'])

    train_tmp = decrease_table_for_last_date(train_tmp)
    score = contest_metric(train[target_name].values, overall_train_predictions)
    print('Total score day {} full: {:.6f}'.format(day, score))
    score = contest_metric(train_tmp[target_name].values, train_tmp['pred'].values)
    print('Total score day {} last date only: {:.6f}'.format(day, score))

    return overall_train_predictions, score, model_list, imp


def predict_with_xgboost_model(test, features, model_list):
    import xgboost as xgb

    dtest = xgb.DMatrix(test[features].values)
    full_preds = []
    for m in model_list:
        preds = m.predict(dtest, ntree_limit=m.best_iteration + 1)
        full_preds.append(preds)
    preds = np.array(full_preds).mean(axis=0)
    if USE_DIFF:
        if USE_LOG:
            if USE_DIV:
                preds *= (np.log10(test['case_day_minus_0'] + 1) + 1)
            else:
                preds += np.log10(test['case_day_minus_0'] + 1)
        else:
            if USE_DIV:
                preds *= (test['case_day_minus_0'] + 1)
            else:
                preds += (test['case_day_minus_0'] + 1)

    if USE_LOG:
        preds = np.power(10, preds) - 1

    preds[preds < 0] = 0

    return preds


if __name__ == '__main__':
    start_time = time.time()
    prediction_type = 'rus_regions'
    gbm_type = 'XGB'
    params = get_params()
    target = params['target']
    id = params['id']
    metric = params['metric']
    limit_date = DAYS_TO_PREDICT

    all_scores = dict()
    alldays_preds_train = dict()
    alldays_preds_test = dict()
    for type in ['confirmed', 'deaths']:
        print('Go for type: {}'.format(type))
        alldays_preds_train[type] = []
        alldays_preds_test[type] = []
        for day in range(1, limit_date+1):
            train, test, features = read_input_data(day, type, step_back_days=STEP_BACK)
            print('Features: [{}] {}'.format(len(features), features))
            print('Test date: {}'.format(sorted(test['date'].unique())))

            if 0:
                train[features].to_csv(CACHE_PATH + 'train_debug.csv')
                test[features].to_csv(CACHE_PATH + 'test_debug.csv')
                exit()

            if 1:
                overall_train_predictions, score, model_list, importance = create_xgboost_model(train, features, params, day)
                prefix = '{}_day_{}_{}_{:.6f}'.format(gbm_type, day, len(model_list), score)
                save_in_file((score, model_list, importance, overall_train_predictions), MODELS_PATH + prefix + '.pklz')
            else:
                prefix = 'XGB_day_1_7_0.011234'
                score, model_list, importance, overall_train_predictions = load_from_file(MODELS_PATH + prefix + '.pklz')

            all_scores[(type, day)] = score
            train['pred'] = overall_train_predictions
            train['pred'] = np.maximum(train['pred'], train['case_day_minus_0'])
            train[['name1', 'name2', 'date', 'target', 'pred']].to_csv(SUBM_PATH_DETAILED + prefix + '_train.csv', index=False, float_format='%.8f')
            train_tmp = decrease_table_for_last_date(train)
            alldays_preds_train[type].append(train_tmp[['name1', 'name2', 'date', 'target', 'pred']].copy())

            overall_test_predictions = predict_with_xgboost_model(test, features, model_list)
            test['pred'] = overall_test_predictions

            # We now that value must be equal or higher
            count_less = (test['pred'] < test['case_day_minus_0']).astype(np.int32).sum()
            if count_less > 0:
                print('Values less than needed for test: {} ({:.4f} %)'.format(count_less, 100 * count_less / len(test)))
            test['pred'] = np.maximum(test['pred'], test['case_day_minus_0'])

            test['shift_day'] = day
            test[['name1', 'name2', 'date', 'pred']].to_csv(SUBM_PATH_DETAILED + prefix + '_test.csv', index=False, float_format='%.8f')
            alldays_preds_test[type].append(test[['name1', 'name2', 'date', 'shift_day', 'pred']].copy())
            print('----------------------------------')

        train = pd.concat(alldays_preds_train[type], axis=0)
        score = contest_metric(train['target'].values, train['pred'].values)
        all_scores[(type, 'full')] = score
        print('Total score {} for all days: {:.6f}'.format(type, score))
        prefix = '{}_{}_all_days_{}_{:.6f}'.format(gbm_type, type, len(model_list), score)
        train.to_csv(SUBM_PATH + '{}_train.csv'.format(prefix), index=False)
        test = pd.concat(alldays_preds_test[type], axis=0)
        test.to_csv(SUBM_PATH + '{}_test.csv'.format(prefix), index=False)

        # Needed for ensemble
        prefix_2 = '{}_{}_LOG_{}_DIFF_{}_DIV_{}_{}'.format(gbm_type, type, USE_LOG, USE_DIFF, USE_DIV, prediction_type)
        train.to_csv(SUBM_PATH + '{}_train.csv'.format(prefix_2), index=False)
        test.to_csv(SUBM_PATH + '{}_test.csv'.format(prefix_2), index=False)

    for type in ['confirmed', 'deaths']:
        for day in range(1, limit_date + 1):
            print('Type: {} Day: {} Score: {:.6f}'.format(type, day, all_scores[(type, day)]))
    for type in ['confirmed', 'deaths']:
        print('Total score {} for all days: {:.6f}'.format(type, all_scores[(type, 'full')]))

    print("Elapsed time overall: {:.2f} seconds".format((time.time() - start_time)))


"""
Test date: ['2020.04.15']
Lag 7 days 99 features
Type: confirmed Day: 1 Score: 0.071139
Type: confirmed Day: 2 Score: 0.079233
Type: confirmed Day: 3 Score: 0.086110
Type: confirmed Day: 4 Score: 0.095523
Type: confirmed Day: 5 Score: 0.090222
Type: confirmed Day: 6 Score: 0.102074
Type: confirmed Day: 7 Score: 0.110018
Type: deaths Day: 1 Score: 0.052967
Type: deaths Day: 2 Score: 0.065003
Type: deaths Day: 3 Score: 0.074598
Type: deaths Day: 4 Score: 0.068727
Type: deaths Day: 5 Score: 0.077558
Type: deaths Day: 6 Score: 0.065138
Type: deaths Day: 7 Score: 0.068895
Total score confirmed for all days: 0.090617
Total score deaths for all days: 0.067555
Elapsed time overall: 1645.94 seconds

Real values: 
Type: confirmed Day: 2020-04-16 Score: 0.085117
Type: confirmed Day: 2020-04-17 Score: 0.094201
Type: confirmed Day: 2020-04-18 Score: 0.125696
Type: confirmed Day: 2020-04-19 Score: 0.151161
Type: confirmed Day: 2020-04-20 Score: 0.169928
Type: confirmed Day: 2020-04-21 Score: 0.186096
Type: confirmed Day: 2020-04-22 Score: 0.185366
Type: deaths Day: 2020-04-16 Score: 0.222074
Type: deaths Day: 2020-04-17 Score: 0.219731
Type: deaths Day: 2020-04-18 Score: 0.221090
Type: deaths Day: 2020-04-19 Score: 0.235673
Type: deaths Day: 2020-04-20 Score: 0.232949
Type: deaths Day: 2020-04-21 Score: 0.248423
Type: deaths Day: 2020-04-22 Score: 0.262757
Real score: Score confirmed: 0.142509 Score deaths: 0.234671 Score overall: 0.188590

Test date: ['2020.04.15']
Lag 7 days 71 features
Type: confirmed Day: 1 Score: 0.073764
Type: confirmed Day: 2 Score: 0.079260
Type: confirmed Day: 3 Score: 0.087129
Type: confirmed Day: 4 Score: 0.095363
Type: confirmed Day: 5 Score: 0.090973
Type: confirmed Day: 6 Score: 0.097639
Type: confirmed Day: 7 Score: 0.106062
Type: deaths Day: 1 Score: 0.051956
Type: deaths Day: 2 Score: 0.067135
Type: deaths Day: 3 Score: 0.072413
Type: deaths Day: 4 Score: 0.073799
Type: deaths Day: 5 Score: 0.074316
Type: deaths Day: 6 Score: 0.064781
Type: deaths Day: 7 Score: 0.070218
Total score confirmed for all days: 0.090027
Total score deaths for all days: 0.067803
Elapsed time overall: 1329.61 seconds

Type: confirmed Day: 2020-04-16 Score: 0.086848
Type: confirmed Day: 2020-04-17 Score: 0.092406
Type: confirmed Day: 2020-04-18 Score: 0.118908
Type: confirmed Day: 2020-04-19 Score: 0.149778
Type: confirmed Day: 2020-04-20 Score: 0.168996
Type: confirmed Day: 2020-04-21 Score: 0.175773
Type: confirmed Day: 2020-04-22 Score: 0.178649
Type: deaths Day: 2020-04-16 Score: 0.222460
Type: deaths Day: 2020-04-17 Score: 0.225574
Type: deaths Day: 2020-04-18 Score: 0.224386
Type: deaths Day: 2020-04-19 Score: 0.236047
Type: deaths Day: 2020-04-20 Score: 0.236699
Type: deaths Day: 2020-04-21 Score: 0.250047
Type: deaths Day: 2020-04-22 Score: 0.259530
Score confirmed: 0.138765 Score deaths: 0.236392 Score overall: 0.187579

Test date: ['2020.04.15']
Lag 7 days 91 features - linear_interpol and density and area
Type: confirmed Day: 1 Score: 0.072374
Type: confirmed Day: 2 Score: 0.079434
Type: confirmed Day: 3 Score: 0.086945
Type: confirmed Day: 4 Score: 0.094579
Type: confirmed Day: 5 Score: 0.089103
Type: confirmed Day: 6 Score: 0.098356
Type: confirmed Day: 7 Score: 0.104675
Type: deaths Day: 1 Score: 0.054862
Type: deaths Day: 2 Score: 0.062332
Type: deaths Day: 3 Score: 0.071120
Type: deaths Day: 4 Score: 0.071400
Type: deaths Day: 5 Score: 0.076250
Type: deaths Day: 6 Score: 0.064880
Type: deaths Day: 7 Score: 0.068240
Total score confirmed for all days: 0.089352
Total score deaths for all days: 0.067012
Elapsed time overall: 1327.81 seconds

Type: confirmed Day: 2020-04-16 Score: 0.083967
Type: confirmed Day: 2020-04-17 Score: 0.088891
Type: confirmed Day: 2020-04-18 Score: 0.113780
Type: confirmed Day: 2020-04-19 Score: 0.144324
Type: confirmed Day: 2020-04-20 Score: 0.154581
Type: confirmed Day: 2020-04-21 Score: 0.161545
Type: confirmed Day: 2020-04-22 Score: 0.168350
Type: deaths Day: 2020-04-16 Score: 0.226474
Type: deaths Day: 2020-04-17 Score: 0.222948
Type: deaths Day: 2020-04-18 Score: 0.226500
Type: deaths Day: 2020-04-19 Score: 0.241678
Type: deaths Day: 2020-04-20 Score: 0.249721
Type: deaths Day: 2020-04-21 Score: 0.262441
Type: deaths Day: 2020-04-22 Score: 0.276438
Score confirmed: 0.130777 Score deaths: 0.243743 Score overall: 0.187260

Lower params - XGB
Test date: ['2020.04.15']
Lag 7 days 91 features - linear_interpol and density and area
Type: confirmed Day: 1 Score: 0.068152
Type: confirmed Day: 2 Score: 0.078076
Type: confirmed Day: 3 Score: 0.100731
Type: confirmed Day: 4 Score: 0.110035
Type: confirmed Day: 5 Score: 0.110679
Type: confirmed Day: 6 Score: 0.127322
Type: confirmed Day: 7 Score: 0.116024
Type: deaths Day: 1 Score: 0.051986
Type: deaths Day: 2 Score: 0.065789
Type: deaths Day: 3 Score: 0.071134
Type: deaths Day: 4 Score: 0.073223
Type: deaths Day: 5 Score: 0.082229
Type: deaths Day: 6 Score: 0.080814
Type: deaths Day: 7 Score: 0.079926
Total score confirmed for all days: 0.101574
Total score deaths for all days: 0.072157
Elapsed time overall: 871.33 seconds

Type: confirmed Day: 2020-04-16 Score: 0.076925
Type: confirmed Day: 2020-04-17 Score: 0.089777
Type: confirmed Day: 2020-04-18 Score: 0.128984
Type: confirmed Day: 2020-04-19 Score: 0.153507
Type: confirmed Day: 2020-04-20 Score: 0.182961
Type: confirmed Day: 2020-04-21 Score: 0.261525
Type: confirmed Day: 2020-04-22 Score: 0.245400
Type: deaths Day: 2020-04-16 Score: 0.213732
Type: deaths Day: 2020-04-17 Score: 0.219880
Type: deaths Day: 2020-04-18 Score: 0.224028
Type: deaths Day: 2020-04-19 Score: 0.239286
Type: deaths Day: 2020-04-20 Score: 0.241331
Type: deaths Day: 2020-04-21 Score: 0.256177
Type: deaths Day: 2020-04-22 Score: 0.271072
Score confirmed: 0.162726 Score deaths: 0.237929 Score overall: 0.200327


Type: confirmed Day: 1 Score: 0.069158
Type: confirmed Day: 2 Score: 0.076217
Type: confirmed Day: 3 Score: 0.085324
Type: confirmed Day: 4 Score: 0.095884
Type: confirmed Day: 5 Score: 0.090220
Type: confirmed Day: 6 Score: 0.101104
Type: confirmed Day: 7 Score: 0.107914
Type: deaths Day: 1 Score: 0.052904
Type: deaths Day: 2 Score: 0.062494
Type: deaths Day: 3 Score: 0.075084
Type: deaths Day: 4 Score: 0.065344
Type: deaths Day: 5 Score: 0.077799
Type: deaths Day: 6 Score: 0.062164
Type: deaths Day: 7 Score: 0.070163
Total score confirmed for all days: 0.089403
Total score deaths for all days: 0.066565
Elapsed time overall: 1340.81 seconds

Type: confirmed Day: 2020-04-16 Score: 0.077298
Type: confirmed Day: 2020-04-17 Score: 0.089779
Type: confirmed Day: 2020-04-18 Score: 0.119170
Type: confirmed Day: 2020-04-19 Score: 0.144981
Type: confirmed Day: 2020-04-20 Score: 0.159309
Type: confirmed Day: 2020-04-21 Score: 0.168596
Type: confirmed Day: 2020-04-22 Score: 0.172268
Type: deaths Day: 2020-04-16 Score: 0.215005
Type: deaths Day: 2020-04-17 Score: 0.218904
Type: deaths Day: 2020-04-18 Score: 0.221531
Type: deaths Day: 2020-04-19 Score: 0.238759
Type: deaths Day: 2020-04-20 Score: 0.244224
Type: deaths Day: 2020-04-21 Score: 0.257685
Type: deaths Day: 2020-04-22 Score: 0.273437
Score confirmed: 0.133057 Score deaths: 0.238506 Score overall: 0.185782

Test date: ['2020.04.17'] - 101 features. Lag 7
Type: confirmed Day: 1 Score: 0.048630
Type: confirmed Day: 2 Score: 0.072937
Type: confirmed Day: 3 Score: 0.078603
Type: confirmed Day: 4 Score: 0.080723
Type: confirmed Day: 5 Score: 0.094411
Type: confirmed Day: 6 Score: 0.100766
Type: confirmed Day: 7 Score: 0.100641
Type: deaths Day: 1 Score: 0.062339
Type: deaths Day: 2 Score: 0.067161
Type: deaths Day: 3 Score: 0.074520
Type: deaths Day: 4 Score: 0.079111
Type: deaths Day: 5 Score: 0.079996
Type: deaths Day: 6 Score: 0.075829
Type: deaths Day: 7 Score: 0.076190
Total score confirmed for all days: 0.082387
Total score deaths for all days: 0.073592
Elapsed time overall: 1195.83 seconds

Type: confirmed Day: 2020-04-18 Score: 0.045406
Type: confirmed Day: 2020-04-19 Score: 0.065422
Type: confirmed Day: 2020-04-20 Score: 0.076352
Type: confirmed Day: 2020-04-21 Score: 0.092924
Type: confirmed Day: 2020-04-22 Score: 0.106660
Type: confirmed Day: 2020-04-23 Score: 0.115557
Type: confirmed Day: 2020-04-24 Score: 0.126919
Type: deaths Day: 2020-04-18 Score: 0.195552
Type: deaths Day: 2020-04-19 Score: 0.227845
Type: deaths Day: 2020-04-20 Score: 0.247049
Type: deaths Day: 2020-04-21 Score: 0.249519
Type: deaths Day: 2020-04-22 Score: 0.260386
Type: deaths Day: 2020-04-23 Score: 0.274442
Type: deaths Day: 2020-04-24 Score: 0.281612
Score confirmed: 0.089891 Score deaths: 0.248058 Score overall: 0.168975
"""