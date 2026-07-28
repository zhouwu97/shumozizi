% NIPT Q2 MATLAB independent modeling and visual smoke run.
% Input: problem/attachments/attachments/附件.xlsx (raw competition attachment)
% Units: gestational week in weeks; BMI in kg/m^2; Y concentration as fraction.
% Command: matlab -batch "run('code/matlab/run_analysis.m')"

runDir = getenv('SHUMOZIZI_RUN_DIR');
assert(strlength(runDir) > 0, 'SHUMOZIZI_RUN_DIR is required');
inputPath = fullfile(runDir, 'problem', 'attachments', 'attachments', '附件.xlsx');
resultDir = fullfile(runDir, 'results', 'matlab');
figureDir = fullfile(runDir, 'figures', 'current');
assert(isfile(inputPath), 'Raw NIPT attachment is missing: %s', inputPath);
if ~isfolder(resultDir), mkdir(resultDir); end
if ~isfolder(figureDir), mkdir(figureDir); end

raw = readtable(inputPath, 'Sheet', '男胎检测数据', 'VariableNamingRule', 'preserve');
mother = string(raw{:, 2});
week = parseGestationalWeek(string(raw{:, 10}));
bmi = double(raw{:, 11});
yConcentration = double(raw{:, 22});
valid = mother ~= "" & isfinite(week) & isfinite(bmi) & isfinite(yConcentration);
mother = mother(valid);
week = week(valid);
bmi = bmi(valid);
yConcentration = yConcentration(valid);

% 同一孕妇同一名义孕周可能有重复测量；先聚合，避免技术重复被当作独立样本。
[groupId, motherAgg, weekAgg] = findgroups(mother, week);
bmiAgg = splitapply(@median, bmi, groupId);
yAgg = splitapply(@median, yConcentration, groupId);
successAgg = yAgg >= 0.04;

modelTable = table(weekAgg, bmiAgg, successAgg, ...
    'VariableNames', {'Week', 'BMI', 'Success'});
mdl = fitglm(modelTable, 'Success ~ Week + BMI + Week:BMI', ...
    'Distribution', 'binomial', 'Link', 'logit');

% 每位孕妇的首次 BMI 用于定义三组，避免后续体重变化泄漏到分组基线。
[~, order] = sortrows(table(motherAgg, weekAgg), {'motherAgg', 'weekAgg'});
motherSorted = motherAgg(order);
bmiSorted = bmiAgg(order);
[~, firstIndex] = unique(motherSorted, 'stable');
baselineBmi = bmiSorted(firstIndex);
cuts = quantile(baselineBmi, [1/3, 2/3]);
edges = [-inf, cuts, inf];
groupBmi = zeros(1, 3);
for g = 1:3
    inGroup = baselineBmi > edges(g) & baselineBmi <= edges(g + 1);
    groupBmi(g) = median(baselineBmi(inGroup));
end

candidateWeeks = (11:0.5:25)';
groupProbability = zeros(numel(candidateWeeks), 3);
for g = 1:3
    predictTable = table(candidateWeeks, repmat(groupBmi(g), numel(candidateWeeks), 1), ...
        'VariableNames', {'Week', 'BMI'});
    groupProbability(:, g) = predict(mdl, predictTable);
end

% 穷举三组动作形成 exact 决策集合，MATLAB 不读取 Python 候选或搜索历史。
[i1, i2, i3] = ndgrid(1:numel(candidateWeeks));
i1 = i1(:); i2 = i2(:); i3 = i3(:);
weekG1 = candidateWeeks(i1);
weekG2 = candidateWeeks(i2);
weekG3 = candidateWeeks(i3);
pG1 = groupProbability(i1, 1);
pG2 = groupProbability(i2, 2);
pG3 = groupProbability(i3, 3);
meanWeek = (weekG1 + weekG2 + weekG3) / 3;
worstFailure = max([1 - pG1, 1 - pG2, 1 - pG3], [], 2);
reliabilityThreshold = 0.85;
feasible = pG1 >= reliabilityThreshold & pG2 >= reliabilityThreshold ...
    & pG3 >= reliabilityThreshold;

% 对相同平均孕周只保留最小失败率，再取严格改善的下包络。
[uniqueWeek, ~, uniqueGroup] = unique(meanWeek);
bestFailureAtWeek = accumarray(uniqueGroup, worstFailure, [], @min);
frontMask = false(size(uniqueWeek));
runningBest = inf;
for k = 1:numel(uniqueWeek)
    if bestFailureAtWeek(k) < runningBest - 1e-12
        frontMask(k) = true;
        runningBest = bestFailureAtWeek(k);
    end
end
frontWeek = uniqueWeek(frontMask);
frontFailure = bestFailureAtWeek(frontMask);

feasibleIndex = find(feasible);
assert(~isempty(feasibleIndex), 'No policy satisfies the 0.85 group reliability constraint');
feasibleWeek = meanWeek(feasibleIndex);
feasibleFailure = worstFailure(feasibleIndex);
weekScale = max(feasibleWeek) - min(feasibleWeek);
failureScale = max(feasibleFailure) - min(feasibleFailure);
if weekScale == 0, weekScale = 1; end
if failureScale == 0, failureScale = 1; end
distanceToIdeal = sqrt(((feasibleWeek - min(feasibleWeek)) / weekScale).^2 ...
    + ((feasibleFailure - min(feasibleFailure)) / failureScale).^2);
[~, localBest] = min(distanceToIdeal);
bestIndex = feasibleIndex(localBest);
bestWeeks = [weekG1(bestIndex), weekG2(bestIndex), weekG3(bestIndex)];
bestProbability = [pG1(bestIndex), pG2(bestIndex), pG3(bestIndex)];

baselineWeeks = [20, 20, 20];
baselineProbability = zeros(1, 3);
fallbackWeeks = zeros(1, 3);
fallbackProbability = zeros(1, 3);
for g = 1:3
    baselineProbability(g) = predict(mdl, ...
        table(20, groupBmi(g), 'VariableNames', {'Week', 'BMI'}));
    fallbackPosition = find(groupProbability(:, g) >= 0.80, 1, 'first');
    if isempty(fallbackPosition), fallbackPosition = numel(candidateWeeks); end
    fallbackWeeks(g) = candidateWeeks(fallbackPosition);
    fallbackProbability(g) = groupProbability(fallbackPosition, g);
end

candidateTable = table(weekG1, weekG2, weekG3, pG1, pG2, pG3, ...
    meanWeek, worstFailure, feasible);
writetable(candidateTable, fullfile(resultDir, 'result.csv'));

result = struct();
result.schema_version = '1.0';
result.question_id = 'Q2';
result.model = 'binomial GLM with Week, BMI, and interaction';
result.independence_boundary = [ ...
    'Reads the raw XLSX only; it does not import Python candidates, fitted parameters, ', ...
    'search histories, or intermediate arrays.'];
result.group_bmi = groupBmi;
result.reliability_threshold = reliabilityThreshold;
result.best_solution = struct( ...
    'recommended_weeks', bestWeeks, ...
    'group_success_probability', bestProbability, ...
    'active_constraints', find(bestProbability <= reliabilityThreshold + 0.02));
result.baseline = struct('recommended_weeks', baselineWeeks, ...
    'group_success_probability', baselineProbability);
result.fallback = struct('recommended_weeks', fallbackWeeks, ...
    'group_success_probability', fallbackProbability, ...
    'reliability_threshold', 0.80);
result.pareto_points = struct('mean_week', frontWeek, 'worst_failure_rate', frontFailure);
result.metrics = struct( ...
    'mean_recommended_week', mean(bestWeeks), ...
    'worst_group_success_rate', min(bestProbability), ...
    'feasible_policy_count', sum(feasible), ...
    'pareto_point_count', numel(frontWeek));
jsonText = jsonencode(result, 'PrettyPrint', true);
fileId = fopen(fullfile(resultDir, 'result.json'), 'w', 'n', 'UTF-8');
assert(fileId ~= -1, 'Cannot open MATLAB result JSON for writing');
cleanupFile = onCleanup(@() fclose(fileId));
fwrite(fileId, jsonText, 'char');
clear cleanupFile;

% 三面板形成“概率结构 -> 可行折中 -> 分组决策”的连续证据链。
figureHandle = figure('Color', 'w', 'Position', [100, 100, 1500, 470]);
layout = tiledlayout(1, 3, 'TileSpacing', 'compact', 'Padding', 'compact');

nexttile(layout, 1);
bmiGrid = linspace(prctile(bmiAgg, 1), prctile(bmiAgg, 99), 70);
weekGrid = linspace(11, 25, 70);
[weekMesh, bmiMesh] = meshgrid(weekGrid, bmiGrid);
surfaceTable = table(weekMesh(:), bmiMesh(:), ...
    'VariableNames', {'Week', 'BMI'});
probabilitySurface = reshape(predict(mdl, surfaceTable), size(weekMesh));
contourf(weekMesh, bmiMesh, probabilitySurface, 16, 'LineStyle', 'none');
hold on;
contour(weekMesh, bmiMesh, probabilitySurface, [0.80, 0.85, 0.90], ...
    'LineColor', [0.1, 0.1, 0.1], 'LineWidth', 1.0, 'ShowText', 'on');
scatter(bestWeeks, groupBmi, 80, [0.85, 0.15, 0.12], 'filled', ...
    'MarkerEdgeColor', 'w', 'LineWidth', 1.0);
xlabel('Gestational week'); ylabel('Baseline BMI');
title('(a) Success-probability surface');
colorbar;
grid on; box on;

nexttile(layout, 2);
sampleStep = max(1, floor(numel(meanWeek) / 4500));
sampleIndex = 1:sampleStep:numel(meanWeek);
feasibleSample = sampleIndex(feasible(sampleIndex));
hFeasible = scatter(meanWeek(feasibleSample), ...
    worstFailure(feasibleSample), 8, [0.24, 0.58, 0.72], ...
    'filled', 'MarkerFaceAlpha', 0.22);
hold on;
infeasibleSample = sampleIndex(~feasible(sampleIndex));
hInfeasible = scatter(meanWeek(infeasibleSample), worstFailure(infeasibleSample), 6, ...
    [0.72, 0.72, 0.72], 'filled', 'MarkerFaceAlpha', 0.12);
hFront = plot(frontWeek, frontFailure, '-', 'Color', [0.08, 0.32, 0.52], 'LineWidth', 2.0);
hSelected = scatter(meanWeek(bestIndex), worstFailure(bestIndex), 110, [0.85, 0.15, 0.12], ...
    'p', 'filled', 'MarkerEdgeColor', 'w');
hBaseline = scatter(mean(baselineWeeks), max(1 - baselineProbability), 80, ...
    [0.12, 0.12, 0.12], 's', 'filled', 'MarkerEdgeColor', 'w');
hFallback = scatter(mean(fallbackWeeks), max(1 - fallbackProbability), 80, ...
    [0.58, 0.25, 0.62], 'd', 'filled', 'MarkerEdgeColor', 'w');
yline(1 - reliabilityThreshold, '--', 'Reliability constraint', ...
    'HandleVisibility', 'off', ...
    'Color', [0.75, 0.20, 0.18]);
xlabel('Mean recommended week'); ylabel('Worst-group failure rate');
title('(b) Feasible region and Pareto front');
legend([hFeasible, hInfeasible, hFront, hSelected, hBaseline, hFallback], ...
    {'Feasible candidates', 'Infeasible candidates', 'Pareto front', ...
    'Selected compromise', 'Common-week baseline', '0.80 fallback'}, ...
    'Location', 'northeast');
grid on; box on;

nexttile(layout, 3);
colors = lines(3);
hold on;
groupLines = gobjects(1, 3);
for g = 1:3
    groupLines(g) = plot(candidateWeeks, groupProbability(:, g), 'Color', colors(g, :), ...
        'LineWidth', 1.8, 'DisplayName', sprintf('BMI group %d', g));
    scatter(bestWeeks(g), bestProbability(g), 65, colors(g, :), 'filled', ...
        'MarkerEdgeColor', 'w', 'HandleVisibility', 'off');
end
hConstraint = yline(reliabilityThreshold, '--', '0.85 hard constraint', ...
    'Color', [0.75, 0.20, 0.18], 'LineWidth', 1.2);
xlabel('Gestational week'); ylabel('Predicted success probability');
title('(c) Group decisions and reliability margin');
legend([groupLines, hConstraint], ...
    {'BMI group 1', 'BMI group 2', 'BMI group 3', '0.85 hard constraint'}, ...
    'Location', 'southeast');
ylim([0, 1]); grid on; box on;

exportgraphics(figureHandle, fullfile(figureDir, 'matlab-nipt-q2-pareto.pdf'), ...
    'ContentType', 'vector');
exportgraphics(figureHandle, fullfile(figureDir, 'matlab-nipt-q2-pareto.png'), ...
    'Resolution', 240);
close(figureHandle);

fprintf('MATLAB NIPT Q2 smoke completed: mean week %.3f, worst success %.4f\n', ...
    result.metrics.mean_recommended_week, result.metrics.worst_group_success_rate);

function week = parseGestationalWeek(values)
% 解析形如 11w+6、13w 的孕周文本，保留日级分辨率。
week = nan(size(values));
for idx = 1:numel(values)
    token = regexp(strtrim(values(idx)), '^(\d+)w(?:\+(\d+))?$', 'tokens', 'once');
    if isempty(token), continue; end
    wholeWeeks = str2double(token{1});
    days = 0;
    if numel(token) >= 2 && ~isempty(token{2}), days = str2double(token{2}); end
    week(idx) = wholeWeeks + days / 7;
end
end
