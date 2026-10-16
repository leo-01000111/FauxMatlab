function [npt, scaling] = codeur(y, fs, bits, fmin, fmax, filename)

tfy = fft(y);
tfy = tfy(:);

npt = length(y);
kmin = round(npt*fmin/fs)+1;
kmax = round(npt*fmax/fs)+1;

tfymasq = tfy(kmin:kmax);
tfymasq = [real(tfymasq) imag(tfymasq)];

scaling = max(max(abs(tfymasq)))*1.01;
tfymasq = tfymasq/scaling;

audiowrite(filename, tfymasq, fs, 'BitsPerSample', bits);

end