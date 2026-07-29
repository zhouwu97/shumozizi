% NIPT Q2 MATLAB independent modeling and visual smoke run.
% Input: problem/attachments/attachments/附件.xlsx (raw competition attachment)
% Units: gestational week in weeks; BMI in kg/m^2; Y concentration as fraction.
% Command: matlab -batch "run('code/matlab/run_analysis.m')"

runDir = getenv('SHUMOZIZI_RUN_DIR');
assert(strlength(runDir) > 0, 'SHUMOZIZI_RUN_DIR is required');
inputPath = fullfile(runDir, 'problem', 'attachments', 'attachments', '附件.xlsx');
resultDir = fullfile(runDir, 'results', 'matlab');
addpath(fullfile(runDir, 'code', 'matlab'));
outputStems = split(string(getenv('SHUMOZIZI_FIGURE_OUTPUT_STEMS')), ';');
outputStems = outputStems(strlength(outputStems) > 0);
assert(~isempty(outputStems), 'SHUMOZIZI_FIGURE_OUTPUT_STEMS is required');
figureOutputStem = fullfile(runDir, strrep(outputStems(1), '/', filesep));
assert(isfile(inputPath), 'Raw NIPT attachment is missing: %s', inputPath);
if ~isfolder(resultDir), mkdir(resultDir); end

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

% Pareto 是直接回答，使用双倍面积；两个辅助面板只解释形成机制。
[figureHandle, theme] = shumoviz.paper_figure(17.6, 11.2);
layout = tiledlayout(2, 3, 'TileSpacing', 'compact', 'Padding', 'compact');

axPareto = nexttile(layout, 1, [2, 2]);
hold(axPareto, 'on');
sampleStep = max(1, floor(numel(meanWeek) / 3500));
sampleIndex = 1:sampleStep:numel(meanWeek);
feasibleSample = sampleIndex(feasible(sampleIndex));
infeasibleSample = sampleIndex(~feasible(sampleIndex));
xLimitsPareto = shumoviz.smart_limits( ...
    [meanWeek(sampleIndex); mean(baselineWeeks); mean(fallbackWeeks)], [], 0.05);
yLimitsPareto = shumoviz.smart_limits( ...
    [worstFailure(sampleIndex); 1 - reliabilityThreshold], [], 0.08);
xlim(axPareto, xLimitsPareto);
ylim(axPareto, yLimitsPareto);
patch(axPareto, ...
    [xLimitsPareto(1), xLimitsPareto(2), xLimitsPareto(2), xLimitsPareto(1)], ...
    [1 - reliabilityThreshold, 1 - reliabilityThreshold, yLimitsPareto(2), yLimitsPareto(2)], ...
    [1.0, 0.94, 0.93], 'EdgeColor', 'none', 'HandleVisibility', 'off');
scatter(axPareto, meanWeek(infeasibleSample), worstFailure(infeasibleSample), ...
    7, theme.colors.light_gray, 'filled', 'MarkerFaceAlpha', 0.32, ...
    'HandleVisibility', 'off');
scatter(axPareto, meanWeek(feasibleSample), worstFailure(feasibleSample), ...
    8, theme.colors.sky, 'filled', 'MarkerFaceAlpha', 0.38, ...
    'HandleVisibility', 'off');
plot(axPareto, frontWeek, frontFailure, '-', ...
    'Color', theme.colors.blue, 'LineWidth', 2.2, 'HandleVisibility', 'off');
selectedX = meanWeek(bestIndex);
selectedY = worstFailure(bestIndex);
baselineX = mean(baselineWeeks);
baselineY = max(1 - baselineProbability);
fallbackX = mean(fallbackWeeks);
fallbackY = max(1 - fallbackProbability);
scatter(axPareto, selectedX, selectedY, 105, theme.colors.vermillion, ...
    'p', 'filled', 'MarkerEdgeColor', 'w', 'LineWidth', 0.9, 'HandleVisibility', 'off');
scatter(axPareto, baselineX, baselineY, 55, theme.colors.black, ...
    's', 'filled', 'MarkerEdgeColor', 'w', 'HandleVisibility', 'off');
scatter(axPareto, fallbackX, fallbackY, 62, theme.colors.purple, ...
    'd', 'filled', 'MarkerEdgeColor', 'w', 'HandleVisibility', 'off');
yline(axPareto, 1 - reliabilityThreshold, '--', ...
    'Color', theme.colors.vermillion, 'LineWidth', 1.0, 'HandleVisibility', 'off');
text(axPareto, xLimitsPareto(2) - 0.2, 1 - reliabilityThreshold + 0.002, ...
    '不可行：最差组成功率低于 85%', 'HorizontalAlignment', 'right', ...
    'VerticalAlignment', 'bottom', 'Color', theme.colors.vermillion, 'FontSize', 8.2);
shumoviz.direct_label(axPareto, selectedX, selectedY, ...
    sprintf('正式方案  %.1f 周 / %.1f%%', selectedX, 100 * (1 - selectedY)), ...
    theme.colors.vermillion, [3, -5]);
shumoviz.direct_label(axPareto, baselineX, baselineY, ...
    sprintf('统一 20 周  %.1f%%', 100 * (1 - baselineY)), ...
    theme.colors.black, [3, 4]);
shumoviz.direct_label(axPareto, fallbackX, fallbackY, ...
    sprintf('80%% fallback  %.1f 周', fallbackX), theme.colors.purple, [3, -2]);
xlabel(axPareto, '三组平均推荐孕周');
ylabel(axPareto, '最差组失败概率');
title(axPareto, '(a) 可靠性约束把正式方案推到 Pareto 拐点', ...
    'FontSize', theme.title_size, 'FontWeight', 'bold');
shumoviz.apply_axes(axPareto, theme);

axSurface = nexttile(layout, 3);
bmiGrid = linspace(prctile(bmiAgg, 1), prctile(bmiAgg, 99), 70);
weekGrid = linspace(11, 25, 70);
[weekMesh, bmiMesh] = meshgrid(weekGrid, bmiGrid);
surfaceTable = table(weekMesh(:), bmiMesh(:), ...
    'VariableNames', {'Week', 'BMI'});
probabilitySurface = reshape(predict(mdl, surfaceTable), size(weekMesh));
contourf(axSurface, weekMesh, bmiMesh, probabilitySurface, 12, 'LineStyle', 'none');
hold(axSurface, 'on');
contour(axSurface, weekMesh, bmiMesh, probabilitySurface, [0.80, 0.85, 0.90], ...
    'LineColor', [0.1, 0.1, 0.1], 'LineWidth', 1.0, 'ShowText', 'on');
scatter(axSurface, bestWeeks, groupBmi, 58, theme.colors.vermillion, 'filled', ...
    'MarkerEdgeColor', 'w', 'LineWidth', 1.0);
for g = 1:3
    text(axSurface, bestWeeks(g), groupBmi(g), sprintf('  G%d', g), ...
        'Color', theme.colors.black, 'FontWeight', 'bold', 'FontSize', 8.0);
end
colormap(axSurface, theme.colors.sequential);
colorBar = colorbar(axSurface);
colorBar.Label.String = '达标概率';
colorBar.FontName = theme.font_name;
colorBar.FontSize = 8.0;
xlabel(axSurface, '孕周');
ylabel(axSurface, '基线 BMI');
title(axSurface, '(b) BMI 决定达到同一可靠性的时点', ...
    'FontSize', theme.title_size, 'FontWeight', 'bold');
shumoviz.apply_axes(axSurface, theme);

axGroups = nexttile(layout, 6);
curveColors = [theme.colors.blue; theme.colors.orange; theme.colors.green];
hold(axGroups, 'on');
for g = 1:3
    plot(axGroups, candidateWeeks, groupProbability(:, g), 'Color', curveColors(g, :), ...
        'LineWidth', 1.8, 'HandleVisibility', 'off');
    scatter(axGroups, bestWeeks(g), bestProbability(g), 48, curveColors(g, :), 'filled', ...
        'MarkerEdgeColor', 'w', 'HandleVisibility', 'off');
    text(axGroups, bestWeeks(g), bestProbability(g), sprintf('  %.1f', bestWeeks(g)), ...
        'Color', curveColors(g, :), 'FontWeight', 'bold', 'FontSize', 8.0, ...
        'VerticalAlignment', 'bottom');
    text(axGroups, candidateWeeks(end) + 0.25, groupProbability(end, g), ...
        sprintf('G%d', g), 'Color', curveColors(g, :), ...
        'FontWeight', 'bold', 'VerticalAlignment', 'middle');
end
yline(axGroups, reliabilityThreshold, '--', 'Color', theme.colors.vermillion, ...
    'LineWidth', 1.0, 'HandleVisibility', 'off');
text(axGroups, 26.6, reliabilityThreshold, '85% 硬约束', ...
    'HorizontalAlignment', 'right', 'VerticalAlignment', 'bottom', ...
    'Color', theme.colors.vermillion, 'FontSize', 8.0);
xlim(axGroups, [10.5, 27.0]);
ylim(axGroups, shumoviz.smart_limits( ...
    [groupProbability(:); reliabilityThreshold], [], 0.08));
xlabel(axGroups, '孕周');
ylabel(axGroups, '预测达标概率');
title(axGroups, '(c) 三组推荐周随 BMI 风险依次后移', ...
    'FontSize', theme.title_size, 'FontWeight', 'bold');
shumoviz.apply_axes(axGroups, theme);

axisSpecs(1) = struct( ...
    'axes', axPareto, 'id', 'pareto', 'role', 'primary', ...
    'x_data', [meanWeek(sampleIndex); baselineX; fallbackX], ...
    'y_data', [worstFailure(sampleIndex); selectedY; baselineY; fallbackY; 1 - reliabilityThreshold], ...
    'legend_overlaps_data', false, 'takeaway_annotation', true, ...
    'decision_markers_labeled', true);
axisSpecs(2) = struct( ...
    'axes', axSurface, 'id', 'probability-surface', 'role', 'supporting', ...
    'x_data', weekGrid, 'y_data', bmiGrid, ...
    'legend_overlaps_data', false, 'takeaway_annotation', true, ...
    'decision_markers_labeled', true);
axisSpecs(3) = struct( ...
    'axes', axGroups, 'id', 'group-reliability', 'role', 'supporting', ...
    'x_data', [candidateWeeks; 27], ...
    'y_data', [groupProbability(:); reliabilityThreshold], ...
    'legend_overlaps_data', false, 'takeaway_annotation', true, ...
    'decision_markers_labeled', true);
metadata = struct( ...
    'primary_panel_id', 'pareto', ...
    'colorblind_safe', true, ...
    'locale_consistent', true);
shumoviz.export_candidate( ...
    figureHandle, figureOutputStem, 'q2-matlab-pareto', axisSpecs, metadata);
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
