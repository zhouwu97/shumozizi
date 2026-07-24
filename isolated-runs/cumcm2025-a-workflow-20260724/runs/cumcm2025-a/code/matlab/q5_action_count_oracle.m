% Q5 独立动作数 oracle：用二次方程线段-球相交重算 13/14/15 动作。
% 单位：位置 m，时间 s；运行：matlab -batch "run('code/matlab/q5_action_count_oracle.m')"

clear; close all; clc;
scriptDirectory = fileparts(mfilename('fullpath'));
runRoot = fileparts(fileparts(scriptDirectory));
q5 = jsondecode(fileread(fullfile(runRoot, 'results', 'raw', 'q5.json')));

missileNames = {'M1', 'M2', 'M3'};
missileInitial = [20000, 0, 2000; 19000, 600, 2100; 18000, -600, 1900];
targetPoints = cylinderSamples(72, 9, 5);
actionCounts = 13:15;
[coverage202505, coverage202506] = coverageSeries(q5.action_count_coverage);
[selectedRows, selectedFinalists] = selectFinalists(q5.high_precision_finalists, ...
    coverage202505, coverage202506, actionCounts);
coarseStep = 0.10;
fineStep = 0.05;
coarseScores = zeros(3, 4);
fineScores = zeros(3, 4);

for index = 1:numel(actionCounts)
    actions = selectedRows{index}.actions(:);
    assert(numel(actions) == actionCounts(index), 'finalist 动作数与覆盖记录不一致');
    coarseScores(index, :) = scoreActions(actions, missileNames, ...
        missileInitial, targetPoints, coarseStep);
    fineScores(index, :) = scoreActions(actions, missileNames, ...
        missileInitial, targetPoints, fineStep);
end

pythonObjectives = reshape([selectedFinalists.objective_missile_s], [], 1);
pythonLower = reshape([selectedFinalists.objective_lower_bound_missile_s], [], 1);
pythonUpper = reshape([selectedFinalists.objective_upper_bound_missile_s], [], 1);
maxProductionError = max(abs(fineScores(:, 1) - pythonObjectives));
maxStepDifference = max(abs(fineScores(:, 1) - coarseScores(:, 1)));
pythonIntervalsOverlap = pythonLower(3) <= pythonUpper(2) && ...
    pythonLower(2) <= pythonUpper(3);
matlabGain = fineScores(3, 1) - fineScores(2, 1);
matlabResolution = max(abs(fineScores(2:3, 1) - coarseScores(2:3, 1)));
matlabGainResolved = abs(matlabGain) > matlabResolution;
assert(pythonIntervalsOverlap, 'Python 高精度包络未重叠，不能沿用 14 动作简约结论');

figurePath = fullfile(runRoot, 'figures', 'matlab_q5_action_count_challenge.png');
challengeFigure = figure('Visible', 'off', 'Color', 'w', 'Position', [100 100 1260 560]);
subplot(1, 2, 1);
plot(0:15, [coverage202505.objective_missile_s], '-o', 'LineWidth', 1.5, ...
    'MarkerSize', 4, 'Color', [0.12 0.40 0.68]); hold on;
plot(0:15, [coverage202506.objective_missile_s], '-s', 'LineWidth', 1.5, ...
    'MarkerSize', 4, 'Color', [0.82 0.30 0.16]);
xline(4, '--', '4/5 动作挑战起点', 'LabelVerticalAlignment', 'bottom');
xline(14, ':', '选定 14 动作', 'LabelVerticalAlignment', 'bottom');
xlabel('激活动作数'); ylabel('总有效遮挡 (missile-s)');
title('Python exact scorer：双 seed 全动作数覆盖');
legend('seed 202505', 'seed 202506', 'Location', 'southeast');
grid on; box on; xlim([0 15]); xticks(0:15);

subplot(1, 2, 2);
bar(actionCounts, [pythonObjectives, fineScores(:, 1)], 'grouped'); hold on;
errorbar(actionCounts - 0.15, pythonObjectives, pythonObjectives - pythonLower, ...
    pythonUpper - pythonObjectives, 'k.', 'LineWidth', 1.2, 'CapSize', 8);
plot(actionCounts, coarseScores(:, 1), 'k--o', 'LineWidth', 1.3, ...
    'MarkerFaceColor', 'w');
xlabel('动作数'); ylabel('总有效遮挡 (missile-s)');
title('MATLAB 二次式 oracle：13/14/15 动作挑战');
legend('Python 生产值', 'MATLAB \Deltat=0.05 s', 'MATLAB \Deltat=0.10 s', ...
    'Location', 'southeast');
grid on; box on; xticks(actionCounts);
exportgraphics(challengeFigure, figurePath, 'Resolution', 220);
close(challengeFigure);

payload = struct();
payload.schema_version = '1.0';
payload.question = 'Q5';
payload.engine = version;
payload.oracle_semantics = struct( ...
    'formulation', 'quadratic-segment-sphere-roots-with-endpoint-containment', ...
    'production_formulation', 'projection-clipping-distance', ...
    'target_sample_count', size(targetPoints, 1), ...
    'action_counts', actionCounts, ...
    'time_steps_s', [coarseStep, fineStep], ...
    'finalist_selection', 'best high-precision finalist per action count');
payload.objectives = struct( ...
    'python', pythonObjectives, ...
    'python_lower', pythonLower, ...
    'python_upper', pythonUpper, ...
    'matlab_coarse', coarseScores(:, 1), ...
    'matlab_fine', fineScores(:, 1));
payload.fine_per_missile_s = fineScores(:, 2:4);
payload.metrics = struct( ...
    'objective_13_missile_s', fineScores(1, 1), ...
    'objective_14_missile_s', fineScores(2, 1), ...
    'objective_15_missile_s', fineScores(3, 1), ...
    'gain_14_to_15_missile_s', fineScores(3, 1) - fineScores(2, 1), ...
    'python_14_15_intervals_overlap', pythonIntervalsOverlap, ...
    'matlab_gain_resolution_missile_s', matlabResolution, ...
    'matlab_gain_resolved', matlabGainResolved, ...
    'production_max_abs_error_missile_s', maxProductionError, ...
    'step_refinement_max_abs_difference_missile_s', maxStepDifference);
payload.figure = 'figures/matlab_q5_action_count_challenge.png';
writeJson(fullfile(runRoot, 'results', 'raw', 'q5_matlab_oracle.json'), payload);

figureInfo = dir(figurePath);
receipt = struct( ...
    'schema_version', '1.0', ...
    'renderer', 'MATLAB exportgraphics', ...
    'engine', version, ...
    'source_script', 'code/matlab/q5_action_count_oracle.m', ...
    'output_file', 'figures/matlab_q5_action_count_challenge.png', ...
    'output_bytes', figureInfo.bytes, ...
    'generated_at', char(datetime('now', 'TimeZone', 'UTC', ...
        'Format', 'yyyy-MM-dd''T''HH:mm:ss.SSSXXX')));
writeJson(fullfile(runRoot, 'figures', 'matlab_q5_action_count_challenge.render.json'), receipt);
disp(jsonencode(payload.metrics));

function points = cylinderSamples(nTheta, nZ, nRadial)
    theta = linspace(0, 2*pi, nTheta + 1); theta(end) = [];
    zValues = linspace(0, 10, nZ);
    points = zeros(0, 3);
    for z = zValues
        points = [points; 7*cos(theta(:)), 200 + 7*sin(theta(:)), ...
            z*ones(nTheta, 1)]; %#ok<AGROW>
    end
    for height = [0, 10]
        for radius = linspace(0, 7, nRadial)
            points = [points; radius*cos(theta(:)), 200 + radius*sin(theta(:)), ...
                height*ones(nTheta, 1)]; %#ok<AGROW>
        end
    end
    points = unique(points, 'rows');
end

function score = scoreActions(actions, missileNames, missileInitial, targets, step)
    durations = zeros(1, 3);
    for missileIndex = 1:3
        initial = missileInitial(missileIndex, :);
        horizon = norm(initial) / 300.0;
        events = [0:step:horizon, horizon]; %#ok<NBRAK>
        for actionIndex = 1:numel(actions)
            burst = actions(actionIndex).burst_time_s;
            events = [events, max(0, min(horizon, burst)), ...
                max(0, min(horizon, burst + 20.0))]; %#ok<AGROW>
        end
        times = unique(sort(events));
        covered = false(size(times));
        for timeIndex = 1:numel(times)
            covered(timeIndex) = fullCylinderCovered(times(timeIndex), initial, ...
                actions, targets);
        end
        intervals = logicalIntervals(times, covered, initial, actions, targets);
        if ~isempty(intervals)
            durations(missileIndex) = sum(intervals(:, 2) - intervals(:, 1));
        end
    end
    score = [sum(durations), durations];
end

function intervals = logicalIntervals(times, covered, missileInitial, actions, targets)
    intervals = zeros(0, 2);
    index = 1;
    while index <= numel(times)
        if ~covered(index)
            index = index + 1;
            continue;
        end
        first = index;
        while index < numel(times) && covered(index + 1)
            index = index + 1;
        end
        last = index;
        if first == 1
            left = times(first);
        else
            left = refineBooleanTransition(times(first - 1), times(first), true, ...
                missileInitial, actions, targets);
        end
        if last == numel(times)
            right = times(last);
        else
            right = refineBooleanTransition(times(last), times(last + 1), false, ...
                missileInitial, actions, targets);
        end
        intervals(end + 1, :) = [left, right]; %#ok<AGROW>
        index = index + 1;
    end
end

function boundary = refineBooleanTransition(left, right, rightState, missileInitial, actions, targets)
    for iteration = 1:38
        middle = 0.5 * (left + right);
        state = fullCylinderCovered(middle, missileInitial, actions, targets);
        if state == rightState
            right = middle;
        else
            left = middle;
        end
    end
    boundary = 0.5 * (left + right);
end

function covered = fullCylinderCovered(time, missileInitial, actions, targets)
    horizon = norm(missileInitial) / 300.0;
    if time < 0 || time > horizon
        covered = false;
        return;
    end
    observer = missileInitial * (1.0 - 300.0 * time / norm(missileInitial));
    targetCovered = false(size(targets, 1), 1);
    for actionIndex = 1:numel(actions)
        action = actions(actionIndex);
        burst = action.burst_time_s;
        if time < burst - 1e-12 || time > burst + 20.0 + 1e-12
            continue;
        end
        center = action.burst_point_m(:)' - [0, 0, 3.0 * (time - burst)];
        targetCovered = targetCovered | segmentSphereQuadratic(observer, targets, center, 10.0);
        if all(targetCovered)
            covered = true;
            return;
        end
    end
    covered = all(targetCovered);
end

function intersects = segmentSphereQuadratic(firstPoint, secondPoints, center, radius)
    directions = secondPoints - firstPoint;
    offset = firstPoint - center;
    a = sum(directions.^2, 2);
    b = 2.0 * (directions * offset');
    c = dot(offset, offset) - radius^2;
    discriminant = b.^2 - 4.0 * a * c;
    rootMask = discriminant >= 0.0 & a > 1e-20;
    rootOne = inf(size(a));
    rootTwo = inf(size(a));
    rootOne(rootMask) = (-b(rootMask) - sqrt(discriminant(rootMask))) ./ (2.0*a(rootMask));
    rootTwo(rootMask) = (-b(rootMask) + sqrt(discriminant(rootMask))) ./ (2.0*a(rootMask));
    firstInside = c <= 0.0;
    secondInside = sum((secondPoints - center).^2, 2) <= radius^2;
    intersects = firstInside | secondInside | ...
        (rootOne >= 0.0 & rootOne <= 1.0) | (rootTwo >= 0.0 & rootTwo <= 1.0);
end

function [firstSeries, secondSeries] = coverageSeries(container)
    names = fieldnames(container);
    firstSeries = [];
    secondSeries = [];
    for index = 1:numel(names)
        name = names{index};
        if contains(name, '202505')
            firstSeries = container.(name);
        elseif contains(name, '202506')
            secondSeries = container.(name);
        end
    end
    assert(~isempty(firstSeries) && ~isempty(secondSeries), '无法解析双 seed 覆盖曲线');
end

function [rows, finalists] = selectFinalists(allFinalists, firstSeries, secondSeries, actionCounts)
    rows = cell(numel(actionCounts), 1);
    finalists = repmat(allFinalists(1), numel(actionCounts), 1);
    for index = 1:numel(actionCounts)
        count = actionCounts(index);
        matches = allFinalists([allFinalists.action_count] == count);
        assert(~isempty(matches), '缺少高精度 finalist');
        [~, bestIndex] = max([matches.objective_missile_s]);
        finalist = matches(bestIndex);
        finalists(index) = finalist;
        if finalist.seed == 202505
            rows{index} = firstSeries(count + 1);
        elseif finalist.seed == 202506
            rows{index} = secondSeries(count + 1);
        else
            error('未知 finalist seed');
        end
    end
end

function writeJson(path, payload)
    fid = fopen(path, 'w');
    assert(fid >= 0, '无法写入 JSON');
    cleaner = onCleanup(@() fclose(fid)); %#ok<NASGU>
    fwrite(fid, jsonencode(payload, PrettyPrint=true), 'char');
end
