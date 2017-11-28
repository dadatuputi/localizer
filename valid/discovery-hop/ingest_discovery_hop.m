addpath ../scripts/
% Import all the data
[ data, tests, macs, durations, hop_rates ] = importdataset(pwd);
% Generate performance metrics
[ result_rate, result_bssi ] = results(tests, data, macs, durations);
rmpath ../scripts/

figure

% Display rate data
subplot(2,1,1);
boxplot(result_rate', 'Labels', hop_rates);
xlabel('Hop Rate');
ylabel('Beacons per second');

% Display bssi rate
means = mean(result_bssi, 3);
subplot(2,1,2);
%s = summary(data{test});
% labels = char(s.bssid.Categories);
result_bssi_scaled = bsxfun(@rdivide, means', durations')';
bar(categorical(hop_rates), result_bssi_scaled);
xlabel('BSSI');
ylabel('Beacons per second');
legend(num2str(macs.AP), 'Location', 'bestoutside')
