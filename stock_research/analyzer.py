"""分析层：单因子区分度 + 决策树规则 + 时间切分验证"""
from __future__ import annotations
import pandas as pd
import numpy as np

from .config import OUTPUT_DIR, SPLIT_DATE, TREE_MAX_DEPTH, TREE_MIN_SAMPLES_LEAF


META_COLS = {'code', 'entry_date', 'signal_type'}
LABELS_OF_INTEREST = ('strong', 'breakdown', 'oscillate', 'weak')


def merge_label_feature(labels: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    df = features.merge(
        labels[['code', 'entry_date', 'label']],
        on=['code', 'entry_date'],
        how='inner',
    )
    df = df[df['label'].isin(LABELS_OF_INTEREST)].reset_index(drop=True)
    return df


def get_feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns
            if c not in META_COLS and c != 'label'
            and pd.api.types.is_numeric_dtype(df[c])]


def feature_ranking(df: pd.DataFrame) -> pd.DataFrame:
    """Kruskal-Wallis 多组检验，p 值越小区分度越高"""
    from scipy import stats
    rows = []
    feat_cols = get_feature_cols(df)
    for col in feat_cols:
        groups = []
        for lbl, g in df.groupby('label'):
            v = g[col].dropna().values
            if len(v) >= 5:
                groups.append(v)
        if len(groups) < 2:
            continue
        try:
            h, p = stats.kruskal(*groups)
        except Exception:
            continue
        # 各组中位数
        med = df.groupby('label')[col].median().to_dict()
        rows.append({'feature': col, 'h': h, 'p': p, **{f'med_{k}': med.get(k) for k in LABELS_OF_INTEREST}})
    out = pd.DataFrame(rows).sort_values('p').reset_index(drop=True)
    out.to_csv(OUTPUT_DIR / 'feature_ranking.csv', index=False)
    print(f'[analyzer] feature_ranking saved: top5')
    print(out.head().to_string())
    return out


def fit_tree(df: pd.DataFrame, max_depth: int = TREE_MAX_DEPTH) -> tuple[object, str]:
    from sklearn.tree import DecisionTreeClassifier, export_text
    feat_cols = get_feature_cols(df)
    X = df[feat_cols].fillna(df[feat_cols].median(numeric_only=True))
    y = df['label']
    clf = DecisionTreeClassifier(
        max_depth=max_depth,
        min_samples_leaf=TREE_MIN_SAMPLES_LEAF,
        random_state=42,
    )
    clf.fit(X, y)
    rules = export_text(clf, feature_names=list(feat_cols))
    train_acc = clf.score(X, y)
    out = OUTPUT_DIR / 'tree_rules.txt'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(f'# Decision Tree (max_depth={max_depth}) train_acc={train_acc:.3f}\n\n')
        f.write(f'classes_: {list(clf.classes_)}\n\n')
        f.write(rules)
    print(f'[analyzer] tree -> {out} (train_acc={train_acc:.3f})')
    return clf, rules


def time_split_validation(df: pd.DataFrame) -> dict:
    """以 SPLIT_DATE 为界，前段训练规则，后段验证。"""
    from sklearn.tree import DecisionTreeClassifier
    feat_cols = get_feature_cols(df)
    train = df[df['entry_date'] < SPLIT_DATE]
    test = df[df['entry_date'] >= SPLIT_DATE]
    if len(train) < 30 or len(test) < 10:
        print(f'[analyzer] split skipped: train={len(train)} test={len(test)}')
        return {'train_n': len(train), 'test_n': len(test), 'train_acc': None, 'test_acc': None}
    Xtr = train[feat_cols].fillna(train[feat_cols].median(numeric_only=True))
    Xte = test[feat_cols].fillna(train[feat_cols].median(numeric_only=True))
    clf = DecisionTreeClassifier(max_depth=TREE_MAX_DEPTH,
                                 min_samples_leaf=TREE_MIN_SAMPLES_LEAF,
                                 random_state=42)
    clf.fit(Xtr, train['label'])
    train_acc = clf.score(Xtr, train['label'])
    test_acc = clf.score(Xte, test['label'])
    print(f'[analyzer] time_split: train_n={len(train)} test_n={len(test)} '
          f'train_acc={train_acc:.3f} test_acc={test_acc:.3f}')
    return {
        'train_n': int(len(train)),
        'test_n': int(len(test)),
        'train_acc': float(train_acc),
        'test_acc': float(test_acc),
    }


def analyze_post3_signals(df: pd.DataFrame) -> dict:
    """仅用 post3_* 特征预测 30 日标签，提炼 3 日内可观测到的早期预警规则。"""
    from sklearn.tree import DecisionTreeClassifier, export_text

    post3_cols = [c for c in df.columns if c.startswith('post3_')
                  and pd.api.types.is_numeric_dtype(df[c])]
    if not post3_cols:
        print('[analyzer] no post3_* columns, skip post3 signals')
        return {'post3_n': 0}

    sub = df[df['label'].isin(LABELS_OF_INTEREST)].copy()
    # 简化为二分类：strong vs not_strong（早期预警关心能否提前识别强势股）
    sub['y'] = (sub['label'] == 'strong').astype(int)
    X = sub[post3_cols].fillna(sub[post3_cols].median(numeric_only=True))
    y = sub['y']
    if len(sub) < 20 or y.nunique() < 2:
        print(f'[analyzer] post3 sample too few: n={len(sub)}')
        return {'post3_n': int(len(sub))}

    clf = DecisionTreeClassifier(max_depth=3, min_samples_leaf=TREE_MIN_SAMPLES_LEAF,
                                 random_state=42)
    clf.fit(X, y)
    train_acc = clf.score(X, y)
    rules = export_text(clf, feature_names=list(post3_cols))

    # 各 post3 特征在 strong vs not_strong 的中位数差异
    rows = []
    for col in post3_cols:
        med_strong = sub.loc[sub['y'] == 1, col].median()
        med_other = sub.loc[sub['y'] == 0, col].median()
        rows.append({
            'feature': col,
            'med_strong': med_strong,
            'med_not_strong': med_other,
            'diff': (med_strong - med_other) if pd.notna(med_strong) and pd.notna(med_other) else np.nan,
        })
    out_df = pd.DataFrame(rows).sort_values('diff', key=lambda s: s.abs(), ascending=False)
    csv_path = OUTPUT_DIR / 'post3_early_signal.csv'
    out_df.to_csv(csv_path, index=False)

    txt_path = OUTPUT_DIR / 'post3_early_signal_rules.txt'
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f'# post3-only DecisionTree (depth=3) train_acc={train_acc:.3f}\n')
        f.write(f'# target: strong(1) vs not_strong(0); n={len(sub)}; pos_ratio={y.mean():.3f}\n\n')
        f.write(f'classes_: {list(clf.classes_)}\n\n')
        f.write(rules)

    print(f'[analyzer] post3_signals -> {csv_path}, train_acc={train_acc:.3f}')
    print(out_df.head().to_string())
    return {
        'post3_n': int(len(sub)),
        'post3_train_acc': float(train_acc),
        'post3_pos_ratio': float(y.mean()),
        'post3_top_features': out_df.head(6).to_dict('records'),
        'post3_rules': rules,
    }


def analyze(labels: pd.DataFrame, features: pd.DataFrame) -> dict:
    df = merge_label_feature(labels, features)
    df.to_parquet(OUTPUT_DIR / 'merged.parquet')
    if df.empty:
        print('[analyzer] empty merged set, skip')
        return {'merged_n': 0}
    print(f'[analyzer] merged set: {len(df)} rows, label dist:')
    print(df['label'].value_counts())

    ranking = feature_ranking(df)
    clf, rules = fit_tree(df)
    split = time_split_validation(df)
    post3 = analyze_post3_signals(df)

    return {
        'merged_n': int(len(df)),
        'label_dist': df['label'].value_counts().to_dict(),
        'top_features': ranking.head(10).to_dict('records'),
        'tree_rules': rules,
        'split_validation': split,
        'post3_signals': post3,
    }


if __name__ == '__main__':
    labels = pd.read_parquet(OUTPUT_DIR / 'labels.parquet')
    features = pd.read_parquet(OUTPUT_DIR / 'features.parquet')
    analyze(labels, features)
