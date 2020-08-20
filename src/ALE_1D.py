import numpy as np
import pandas as pd
import random
import matplotlib.pyplot as plt
import matplotlib.transforms as mtrans

from src.lib import quantile_ied, CI_estimate

def aleplot_1D_continuous(X, model, feature, grid_size=40, include_CI=True, C=0.95):
    """Compute the accumulated local effect of a numeric continuous feature.
    
    This function divides the feature in question into grid_size intervals (bins) 
    and computes the difference in prediction between the first and last value 
    of each interval and then centers the results.

    Arguments:
    X -- A pandas DataFrame to pass to the model for prediction.
    model -- Any python model with a predict method that accepts X as input.
    feature -- String, the name of the column holding the feature being studied.
    grid_size -- An integer indicating the number of intervals into which the 
    feature range is divided.
    include_CI -- A boolean, if True the confidence interval 
    of the effect is returned with the results. 
    C -- A float indicating the soze of the confidence interval
    
    Return: A pandas DataFrame containing for each bin: the size of the sample in it
    and the accumulated centered effect of this bin.
    """

    quantiles = np.append(0, np.arange(1 / grid_size, 1 + 1 / grid_size, 1 / grid_size))
    # use customized quantile function to get the same result as
    # type 1 R quantile (Inverse of empirical distribution function)
    bins = [X[feature].min()] + quantile_ied(X[feature], quantiles).to_list()
    bins = np.unique(bins)
    feat_cut = pd.cut(X[feature], bins, include_lowest=True)

    bin_codes = feat_cut.cat.codes
    bin_codes_unique = np.unique(bin_codes)

    X1 = X.copy()
    X2 = X.copy()
    X1[feature] = [bins[i] for i in bin_codes]
    X2[feature] = [bins[i + 1] for i in bin_codes]
    y_1 = model.predict(X1)
    y_2 = model.predict(X2)

    delta_df = pd.DataFrame({feature: bins[bin_codes + 1], "Delta": y_2 - y_1})
    res_df = delta_df.groupby([feature]).Delta.agg(["size", ("eff", "mean")])
    res_df["eff"] = res_df["eff"].cumsum()
    res_df.loc[min(bins), :] = 0
    # subtract the total average of a moving average of size 2
    mean_mv_avg = (
        (res_df["eff"] + res_df["eff"].shift(1, fill_value=0)) / 2 * res_df["size"]
    ).sum() / res_df["size"].sum()
    res_df = res_df.sort_index().assign(eff=res_df["eff"] - mean_mv_avg)
    if include_CI:
        ci_est = delta_df.groupby(feature).Delta.agg(
            [("CI_estimate", lambda x: CI_estimate(x, C=C))]
        )
        # ci_est.loc[min(bins)] = ci_est.iloc[0]
        ci_est = ci_est.sort_index()
        lowerCI_name = "lowerCI_" + str(int(C * 100)) + "%"
        upperCI_name = "upperCI_" + str(int(C * 100)) + "%"
        res_df[lowerCI_name] = res_df[["eff"]].subtract(ci_est["CI_estimate"], axis=0)
        res_df[upperCI_name] = upperCI = res_df[["eff"]].add(
            ci_est["CI_estimate"], axis=0
        )
    return res_df


def aleplot_1D_discrete(X, model, feature):
    """Compute the accumulated local effect of a numeric discrete feature.
    
    This function computes the difference in prediction when the value of the feature
    is replaced once with the value before it and once with the value after it, without 
    the need to divide into interval like the case of aleplot_1D_continuous.

    Arguments:
    X -- A pandas DataFrame to pass to the model for prediction.
    model -- Any python model with a predict method that accepts X as input.
    feature -- String, the name of the column holding the feature being studied.
    
    Return: A pandas DataFrame containing for each value of the feature: the size 
    of the sample in it and the accumulated centered effect around this value.
    """

    groups = X[feature].unique()
    groups.sort()
    groups_codes = [x for x in range(len(groups))]

    groups_counts = X.groupby(feature).size()
    groups_props = groups_counts / sum(groups_counts)

    K = len(groups)

    # create copies of the dataframe
    X_plus = X.copy()
    X_neg = X.copy()
    # all groups except last one
    ind_plus = X[feature] < groups[K - 1]
    # all groups except first one
    ind_neg = X[feature] > groups[0]
    # replace once with one level up
    X_plus.loc[ind_plus, feature] = groups[X.loc[ind_plus, feature] + 1]
    # replace once with one level down
    X_neg.loc[ind_neg, feature] = groups[X.loc[ind_neg, feature] - 1]
    # predict with original and with the replaced values
    y_hat = model.predict(X)
    y_hat_plus = model.predict(X_plus[ind_plus])
    y_hat_neg = model.predict(X_neg[ind_neg])
    # compute prediction difference
    Delta_plus = y_hat_plus - y_hat[ind_plus]
    Delta_neg = y_hat[ind_neg] - y_hat_neg

    # compute the mean of the difference per group
    res_df = pd.concat(
        [
            pd.DataFrame({"Delta": Delta_plus, feature: X.loc[ind_plus, feature] + 1}),
            pd.DataFrame({"Delta": Delta_neg, feature: X.loc[ind_neg, feature]}),
        ]
    )
    res_df = res_df.groupby([feature]).mean()
    res_df["eff"] = res_df["Delta"].cumsum()
    res_df.loc[0] = 0
    res_df = res_df.sort_index()
    res_df["eff"] = res_df["eff"] - sum(res_df["eff"] * groups_props)
    return res_df


def plot_1D_continuous_eff(res_df, X, fig=None, ax=None):
    """Plot the 1D ALE plot for a continuous feature.
    
    Arguments:
    res_df -- A pandas DataFrame containing the computed effects 
    (the output of ale_1D_continuous).
    X -- The dataset used to compute the effects.
    fig, ax -- matplotlib figure and axis.
    """

    feature_name = res_df.index.name
    rug = X[feature_name]
    # position: jitter
    jitter_max_step_per_bin = (res_df.index - res_df.index.to_series().shift(1)) * 0.3
    jitter_max_step = jitter_max_step_per_bin.iloc[
        (
            pd.cut(
                X[feature_name], res_df.index.to_list(), include_lowest=True
            ).cat.codes
            + 1
        ).to_list()
    ]

    random.seed(123)
    rug = [x + random.uniform(-y, y) for x, y in zip(rug, jitter_max_step)]

    if fig is None and ax is None:
        fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(res_df[["eff"]])
    tr = mtrans.offset_copy(ax.transData, fig=fig, x=0.0, y=-5, units="points")
    ax.plot(
        rug,
        [res_df.drop("size", axis=1).min().min()] * len(rug),
        "|",
        color="k",
        alpha=0.2,
        transform=tr,
    )
    lowerCI_name = res_df.columns[res_df.columns.str.contains("lowerCI")]
    upperCI_name = res_df.columns[res_df.columns.str.contains("upperCI")]
    if (len(lowerCI_name) == 1) and (len(upperCI_name) == 1):
        label = lowerCI_name.str.split("_")[0][1] + " confidence interval"
        ax.fill_between(
            res_df.index,
            y1=res_df[lowerCI_name[0]],
            y2=res_df[upperCI_name[0]],
            alpha=0.2,
            color="grey",
            label=label,
        )
        ax.legend()
    ax.set_xlabel(res_df.index.name)
    ax.set_ylabel("Effect on prediction (centered)")
    ax.set_title("1D ALE Plot - Continuous")
    return fig, ax


def plot_1D_discrete_eff(res_df, X, fig=None, ax=None):
    """Plot the 1D ALE plot for a discrete feature.
    
    Arguments:
    res_df -- A pandas DataFrame with the computed effects
    (the output of ale_1D_discrete).
    X -- The dataset used to compute the effects.
    fig, ax -- matplotlib figure and axis.
    """

    feature_name = res_df.index.name
    if fig is None and ax is None:
        fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(res_df.index, res_df["eff"], alpha=0.2)

    ax.set_xlabel(feature_name)
    ax.set_ylabel("Effect on prediction (centered)")
    ax.set_title("1D ALE Plot - Discrete/Categorical")
    return fig, ax