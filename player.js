  var video = document.getElementById('video');
  var vurl = location.search.split('vurl=')[1];
  var videoSrc = vurl;
  // ���������Ƿ�֧��hls
  if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = videoSrc;
  // �粻֧�������hls.min.js
  } else if (Hls.isSupported()) {
    var hls = new Hls();
    hls.loadSource(videoSrc);
    hls.attachMedia(video);
  }