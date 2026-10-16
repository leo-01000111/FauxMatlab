function [f, tfx] = transffourier(y, Nf, fs)
% INPUTS
% y - vector containing the Nt values of the signal
% Nf - number of frequencies
% fs - sampling frequency
% OUTPUTS
% f = array of frequencies (in Hz) for which the transform was calculated
% tfx = approzimation of the fourier transform

y = y(:); %to force it as a collumn vector
k = 0:Nf-1;
f = k/Nf*fs;
YNf = fft(y, Nf);
tfx = YNf/fs;
end