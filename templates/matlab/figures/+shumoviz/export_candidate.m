function outputs = export_candidate(fig, outputStem, figureId, axisSpecs, metadata)
%EXPORT_CANDIDATE 导出 PNG/PDF，并写普通统计图的可机检布局报告。

outputStem = char(outputStem);
figureId = char(figureId);
if nargin < 5, metadata = struct(); end
[folder, ~, ~] = fileparts(outputStem);
if ~isfolder(folder), mkdir(folder); end
pngPath = [outputStem '.png'];
pdfPath = [outputStem '.pdf'];
layoutPath = [outputStem '.layout.json'];
assert(~isfile(pngPath) && ~isfile(pdfPath) && ~isfile(layoutPath), ...
    'Candidate version already exists; use a new version directory');

drawnow;
if exist('exportgraphics', 'file') == 2
    exportgraphics(fig, pdfPath, 'ContentType', 'vector', 'BackgroundColor', 'white');
    exportgraphics(fig, pngPath, 'Resolution', 300, 'BackgroundColor', 'white');
else
    print(fig, pdfPath, '-dpdf', '-painters');
    print(fig, pngPath, '-dpng', '-r300');
end

position = get(fig, 'Position');
fontObjects = findall(fig, '-property', 'FontSize');
fontSizes = nan(numel(fontObjects), 1);
for index = 1:numel(fontObjects)
    fontSizes(index) = double(get(fontObjects(index), 'FontSize'));
end
fontSizes = fontSizes(isfinite(fontSizes) & fontSizes > 0);
assert(~isempty(fontSizes), 'Figure does not expose a positive font size');

report = struct();
report.schema_version = '1.0';
report.figure_id = figureId;
report.paper_size_cm = struct('width', position(3), 'height', position(4));
report.minimum_font_size_pt = min(fontSizes);
report.colorblind_safe = field_or(metadata, 'colorblind_safe', true);
report.locale_consistent = field_or(metadata, 'locale_consistent', true);
report.primary_panel_id = char(field_or(metadata, 'primary_panel_id', axisSpecs(1).id));
if isfield(metadata, 'wide_figure_reason')
    report.wide_figure_reason = char(metadata.wide_figure_reason);
end

axesReport = repmat(struct(), 1, numel(axisSpecs));
for index = 1:numel(axisSpecs)
    spec = axisSpecs(index);
    ax = spec.axes;
    axesReport(index).id = char(spec.id);
    axesReport(index).role = char(spec.role);
    axesReport(index).x_limits = double(ax.XLim);
    axesReport(index).x_data_range = finite_range(spec.x_data);
    axesReport(index).y_limits = double(ax.YLim);
    axesReport(index).y_data_range = finite_range(spec.y_data);
    axesReport(index).projection = char(field_or(spec, 'projection', '2d'));
    if strcmp(axesReport(index).projection, '3d')
        axesReport(index).z_limits = double(ax.ZLim);
        axesReport(index).z_data_range = finite_range(spec.z_data);
        axesReport(index).data_aspect_ratio = double(ax.DataAspectRatio);
        axesReport(index).camera_projection = char( ...
            field_or(spec, 'camera_projection', ''));
        axesReport(index).camera_view = field_or(spec, 'camera_view', struct());
        axesReport(index).coordinate_unit = char(field_or(spec, 'coordinate_unit', ''));
        axesReport(index).trajectory_direction_labeled = logical( ...
            field_or(spec, 'trajectory_direction_labeled', false));
    end
    axesReport(index).legend_overlaps_data = logical( ...
        field_or(spec, 'legend_overlaps_data', false));
    axesReport(index).takeaway_annotation = logical( ...
        field_or(spec, 'takeaway_annotation', false));
    axesReport(index).decision_markers_labeled = logical( ...
        field_or(spec, 'decision_markers_labeled', true));
    if isfield(spec, 'axis_policy')
        axesReport(index).axis_policy = char(spec.axis_policy);
    end
    if isfield(spec, 'low_occupancy_reason')
        axesReport(index).low_occupancy_reason = char(spec.low_occupancy_reason);
    end
end
report.axes = axesReport;

jsonText = jsonencode(report, 'PrettyPrint', true);
fileId = fopen(layoutPath, 'w', 'n', 'UTF-8');
assert(fileId ~= -1, 'Cannot open plot layout report for writing');
cleanupFile = onCleanup(@() fclose(fileId));
fwrite(fileId, jsonText, 'char');
clear cleanupFile;
outputs = struct('png', pngPath, 'pdf', pdfPath, 'layout', layoutPath);
end

function value = field_or(item, fieldName, fallback)
if isfield(item, fieldName)
    value = item.(fieldName);
else
    value = fallback;
end
end

function range = finite_range(values)
values = double(values(:));
values = values(isfinite(values));
assert(~isempty(values), 'Axis report data must contain finite values');
lower = min(values);
upper = max(values);
if upper <= lower
    delta = max(1, abs(lower)) * 1e-9;
    lower = lower - delta;
    upper = upper + delta;
end
range = [lower, upper];
end
