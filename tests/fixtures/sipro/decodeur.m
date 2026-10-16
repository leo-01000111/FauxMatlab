function [y, fs, bits] = decodeur(filename, fmin, fmax, npt, scaling)

[yM, fs] = audioread(filename);
info = audioinfo(filename); 

bits = info.BitsPerSample;

tfymasq = scaling*(yM(:,1)+1j*yM(:,2));

tfy = zeros(npt, 1);

kmin = round(npt*fmin/fs)+1;
kmax = round(npt*fmax/fs)+1;

idx=kmin:kmax;

tfy(idx) = tfymasq;

idx = idx(idx>1);

tfy(npt + 2 - idx) = conj(tfy(idx));

y = real(ifft(tfy));

end

