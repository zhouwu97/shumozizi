% Q1 独立几何 oracle：输入为题面常数和当前生产 Q1 JSON。
% 单位：位置 m，时间 s；运行：matlab -batch "run('code/matlab/q1_geometry_oracle.m')"

clear; close all; clc;
scriptDirectory = fileparts(mfilename('fullpath'));
runRoot = fileparts(fileparts(scriptDirectory));
resultPath = fullfile(runRoot, 'results', 'raw', 'q1.json');
production = jsondecode(fileread(resultPath));

g = 9.8;
radius = 10.0;
burstTime = 5.1;
cloudAtBurst = [17188.0, 0.0, 1800.0 - 0.5 * g * 3.6^2];
missileInitial = [20000.0, 0.0, 2000.0];
missileVelocity = -300.0 * missileInitial / norm(missileInitial);

leftRoot = fzero(@(t) worstCylinderMargin(t, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius), [7.9, 8.2]);
rightRoot = fzero(@(t) worstCylinderMargin(t, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius), [9.3, 9.6]);
[~, leftPoint] = worstCylinderMargin(leftRoot, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius);
[~, rightPoint] = worstCylinderMargin(rightRoot, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius);
duration = rightRoot - leftRoot;

times = linspace(burstTime, burstTime + 20.0, 240);
sampleMargins = arrayfun(@(t) sampledCylinderMargin(t, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius), times);
marginFigure = figure('Visible', 'off', 'Color', 'w', 'Position', [100 100 1100 560]);
plot(times, sampleMargins, 'LineWidth', 1.8, 'Color', [0.10 0.35 0.70]); hold on;
yline(0.0, 'k--', 'LineWidth', 1.2);
plot([leftRoot rightRoot], [0 0], 'o', 'MarkerSize', 8, 'MarkerFaceColor', [0.85 0.20 0.15], 'MarkerEdgeColor', 'none');
xlabel('时间 t (s)'); ylabel('最坏视线二次裕量 (m^2)');
title('MATLAB 独立二次式 oracle：Q1 连续临界区间');
legend('高密度圆柱表面裕量', '零线', '连续优化根', 'Location', 'best');
grid on; box on;
exportgraphics(marginFigure, fullfile(runRoot, 'figures', 'matlab_q1_margin.png'), 'Resolution', 220);
close(marginFigure);

geometryFigure = figure('Visible', 'off', 'Color', 'w', 'Position', [100 100 1250 560]);
renderEndpoint(geometryFigure, 1, leftRoot, leftPoint, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius, '左临界端点');
renderEndpoint(geometryFigure, 2, rightRoot, rightPoint, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius, '右临界端点');
exportgraphics(geometryFigure, fullfile(runRoot, 'figures', 'matlab_q1_endpoints.png'), 'Resolution', 220);
close(geometryFigure);

boundary = runBoundaryCases();
productionLeft = production.metrics.left_endpoint_s;
productionRight = production.metrics.right_endpoint_s;
comparisonError = max(abs([leftRoot - productionLeft, rightRoot - productionRight]));

oracleSemantics = struct( ...
    'schema_name', 'independent_oracle_semantics', ...
    'schema_version', '1.0', ...
    'formulation', 'quadratic-segment-roots-with-endpoint-containment-and-continuous-cylinder-surface-maximization', ...
    'production_formulation', 'projection-clipping-distance-with-deterministic-cylinder-surface-grid', ...
    'boundary_cases', {{'endpoint', 'tangent', 'degenerate', 'inside', 'outside'}}, ...
    'all_cases_compared', true);
payload = struct();
payload.schema_version = '1.0';
payload.question = 'Q1';
payload.engine = version;
payload.oracle_semantics = oracleSemantics;
payload.metrics = struct( ...
    'left_endpoint_s', leftRoot, ...
    'right_endpoint_s', rightRoot, ...
    'duration_s', duration, ...
    'production_endpoint_max_abs_error_s', comparisonError);
payload.critical_target_points_m = struct('left', leftPoint, 'right', rightPoint);
payload.boundary_cases = boundary;
payload.figures = {'figures/matlab_q1_margin.png', 'figures/matlab_q1_endpoints.png'};

outputPath = fullfile(runRoot, 'results', 'raw', 'q1_matlab_oracle.json');
fid = fopen(outputPath, 'w');
assert(fid >= 0, '无法写入 oracle JSON');
cleaner = onCleanup(@() fclose(fid));
fwrite(fid, jsonencode(payload, PrettyPrint=true), 'char');

marginInfo = dir(fullfile(runRoot, 'figures', 'matlab_q1_margin.png'));
endpointInfo = dir(fullfile(runRoot, 'figures', 'matlab_q1_endpoints.png'));
receipt = struct( ...
    'schema_version', '1.0', ...
    'renderer', 'MATLAB exportgraphics', ...
    'engine', version, ...
    'source_script', 'code/matlab/q1_geometry_oracle.m', ...
    'output_files', {{'figures/matlab_q1_margin.png', 'figures/matlab_q1_endpoints.png'}}, ...
    'output_bytes', [marginInfo.bytes, endpointInfo.bytes], ...
    'generated_at', char(datetime('now', 'TimeZone', 'UTC', ...
        'Format', 'yyyy-MM-dd''T''HH:mm:ss.SSSXXX')));
receiptPath = fullfile(runRoot, 'figures', 'matlab_q1.render.json');
receiptFid = fopen(receiptPath, 'w');
assert(receiptFid >= 0, '无法写入渲染收据');
receiptCleaner = onCleanup(@() fclose(receiptFid)); %#ok<NASGU>
fwrite(receiptFid, jsonencode(receipt, PrettyPrint=true), 'char');
disp(jsonencode(payload.metrics));

function [worst, criticalPoint] = worstCylinderMargin(t, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius)
    starts = linspace(0, 2*pi, 13); starts(end) = [];
    bestValues = -inf(1, 3);
    bestPoints = zeros(3, 3);
    options = optimoptions('fmincon', 'Display', 'off', 'Algorithm', 'sqp', ...
        'OptimalityTolerance', 1e-10, 'StepTolerance', 1e-11, 'MaxIterations', 180);
    for surface = 1:3
        for k = 1:numel(starts)
            if surface == 1
                x0 = [starts(k), 5.0]; lb = [0.0, 0.0]; ub = [2*pi, 10.0];
            else
                x0 = [starts(k), 3.5]; lb = [0.0, 0.0]; ub = [2*pi, 7.0];
            end
            objective = @(x) -surfaceMargin(x, surface, t, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius);
            [x, negativeValue] = fmincon(objective, x0, [], [], [], [], lb, ub, [], options);
            value = -negativeValue;
            if value > bestValues(surface)
                bestValues(surface) = value;
                bestPoints(surface, :) = surfacePoint(x, surface);
            end
        end
    end
    [worst, index] = max(bestValues);
    criticalPoint = bestPoints(index, :);
end

function value = surfaceMargin(x, surface, t, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius)
    point = surfacePoint(x, surface);
    observer = missileInitial + missileVelocity * t;
    center = cloudAtBurst + [0.0, 0.0, -3.0 * (t - burstTime)];
    value = quadraticMinimum(center, observer, point) - radius^2;
end

function point = surfacePoint(x, surface)
    if surface == 1
        point = [7.0*cos(x(1)), 200.0 + 7.0*sin(x(1)), x(2)];
    elseif surface == 2
        point = [x(2)*cos(x(1)), 200.0 + x(2)*sin(x(1)), 0.0];
    else
        point = [x(2)*cos(x(1)), 200.0 + x(2)*sin(x(1)), 10.0];
    end
end

function minimum = quadraticMinimum(center, firstPoint, secondPoint)
    direction = secondPoint - firstPoint;
    offset = firstPoint - center;
    a = dot(direction, direction);
    if a <= 1e-20
        minimum = dot(offset, offset);
        return;
    end
    b = 2.0 * dot(offset, direction);
    candidates = [0.0, 1.0, min(1.0, max(0.0, -b/(2.0*a)))];
    values = a*candidates.^2 + b*candidates + dot(offset, offset);
    minimum = min(values);
end

function worst = sampledCylinderMargin(t, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius)
    theta = linspace(0, 2*pi, 361); theta(end) = [];
    z = linspace(0, 10, 41);
    radial = linspace(0, 7, 25);
    points = zeros(0, 3);
    for k = 1:numel(z)
        points = [points; 7*cos(theta(:)), 200 + 7*sin(theta(:)), z(k)*ones(numel(theta),1)]; %#ok<AGROW>
    end
    for height = [0, 10]
        for r = radial
            points = [points; r*cos(theta(:)), 200 + r*sin(theta(:)), height*ones(numel(theta),1)]; %#ok<AGROW>
        end
    end
    observer = missileInitial + missileVelocity * t;
    center = cloudAtBurst + [0.0, 0.0, -3.0 * (t - burstTime)];
    values = zeros(size(points,1),1);
    for index = 1:size(points,1)
        values(index) = quadraticMinimum(center, observer, points(index,:)) - radius^2;
    end
    worst = max(values);
end

function cases = runBoundaryCases()
    cases = struct();
    cases.endpoint = segmentBallQuadratic([-2,0,0], [0,0,0], [0,0,0], 0.5);
    cases.tangent = segmentBallQuadratic([-2,1,0], [2,1,0], [0,0,0], 1.0);
    cases.degenerate = segmentBallQuadratic([0,0,0], [0,0,0], [0,0,0], 1.0);
    cases.inside = segmentBallQuadratic([-0.2,0,0], [0.2,0,0], [0,0,0], 1.0);
    cases.outside = segmentBallQuadratic([2,2,0], [3,2,0], [0,0,0], 1.0);
    assert(cases.endpoint && cases.tangent && cases.degenerate && cases.inside && ~cases.outside);
end

function intersects = segmentBallQuadratic(firstPoint, secondPoint, center, radius)
    direction = secondPoint - firstPoint;
    offset = firstPoint - center;
    a = dot(direction, direction);
    c = dot(offset, offset) - radius^2;
    if a <= 1e-20
        intersects = c <= 0.0;
        return;
    end
    b = 2.0 * dot(offset, direction);
    discriminant = b^2 - 4*a*c;
    endpointInside = c <= 0.0 || dot(secondPoint-center, secondPoint-center) <= radius^2;
    if discriminant < 0.0
        intersects = endpointInside;
        return;
    end
    roots = [(-b-sqrt(max(discriminant,0)))/(2*a), (-b+sqrt(max(discriminant,0)))/(2*a)];
    intersects = endpointInside || any(roots >= 0.0 & roots <= 1.0);
end

function renderEndpoint(parentFigure, index, t, criticalPoint, cloudAtBurst, burstTime, missileInitial, missileVelocity, radius, labelText)
    figure(parentFigure); subplot(1,2,index); hold on;
    observer = missileInitial + missileVelocity * t;
    center = cloudAtBurst + [0.0, 0.0, -3.0*(t-burstTime)];
    sight = criticalPoint - observer;
    sightLength = norm(sight);
    longitudinalUnit = sight / sightLength;
    centerOffset = center - observer;
    centerLongitudinal = dot(centerOffset, longitudinalUnit);
    perpendicularVector = centerOffset - centerLongitudinal*longitudinalUnit;
    centerTransverse = norm(perpendicularVector);
    closestLongitudinal = min(sightLength, max(0.0, centerLongitudinal));
    angle = linspace(0, 2*pi, 300);
    fill(centerLongitudinal + radius*cos(angle), centerTransverse + radius*sin(angle), ...
        [0.18 0.55 0.72], 'FaceAlpha', 0.25, 'EdgeColor', [0.10 0.35 0.55], 'LineWidth', 1.5);
    localLeft = max(0.0, centerLongitudinal - 28.0);
    localRight = min(sightLength, centerLongitudinal + 28.0);
    plot([localLeft localRight], [0 0], 'k-', 'LineWidth', 1.7);
    plot([centerLongitudinal closestLongitudinal], [centerTransverse 0], '--', ...
        'Color', [0.75 0.15 0.12], 'LineWidth', 1.4);
    scatter(centerLongitudinal, centerTransverse, 55, [0.10 0.35 0.55], 'filled');
    scatter(closestLongitudinal, 0, 48, [0.75 0.15 0.12], 'filled');
    text(localLeft + 1.0, -12.5, '导弹方向', 'HorizontalAlignment', 'left');
    text(localRight - 1.0, -12.5, '真目标方向', 'HorizontalAlignment', 'right');
    xlabel('沿导弹-临界目标点视线的纵向坐标 (m)');
    ylabel('视线横向坐标 (m)');
    title(sprintf('%s t=%.6f s，横向距离 %.6f m', labelText, t, centerTransverse));
    axis equal; grid on; box on;
    xlim([localLeft localRight]); ylim([-15 15]);
    legend('烟幕有效截面', '临界视线', '球心至视线', '烟幕中心', '最近点', 'Location', 'best');
end
