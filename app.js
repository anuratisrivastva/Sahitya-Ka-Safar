(function () {
  const svg = d3.select("#map");
  const mapLayer = svg.append("g").attr("class", "map-layer");
  const markersLayer = svg.append("g").attr("class", "markers-layer");

  const overlay = document.getElementById("overlay");
  const card = document.getElementById("book-card");
  const infoCard = document.getElementById("info-card");
  const cardCover = document.getElementById("card-cover");
  const cardCoverFallback = document.getElementById("card-cover-fallback");
  const cardTitle = document.getElementById("card-title");
  const cardAuthor = document.getElementById("card-author");
  const cardPlace = document.getElementById("card-place");
  const counterEl = document.getElementById("counter");
  const banner = document.querySelector(".banner");
  const mapWrap = document.getElementById("map-wrap");

  const ICON_SIZE = 5;
  const ICON_PATHS = {
    cover: "M6 2.5h11a1.5 1.5 0 0 1 1.5 1.5v16a1.5 1.5 0 0 1-1.5 1.5H6A2.5 2.5 0 0 1 3.5 19V5A2.5 2.5 0 0 1 6 2.5Z",
    spine: "M6 2.5v18",
    ribbon: "M13.5 4v5.2l-1.75-1.3L10 9.2V4Z",
  };

  let projection, path, zoom, width, height;
  let activeMarker = null;
  let activeModal = null;

  function size() {
    document.documentElement.style.setProperty("--header-h", `${banner.offsetHeight}px`);
    width = mapWrap.clientWidth;
    height = mapWrap.clientHeight;
    svg.attr("viewBox", [0, 0, width, height]);
  }

  function setupZoom() {
    zoom = d3.zoom()
      .scaleExtent([1, 12])
      .on("zoom", (event) => {
        mapLayer.attr("transform", event.transform);
        markersLayer.attr("transform", event.transform);
      });
    svg.call(zoom);
  }

  function positionMarkers() {
    markersLayer.selectAll(".marker-group")
      .attr("transform", (d) => {
        const [x, y] = projection([d.lon, d.lat]);
        return `translate(${x},${y})`;
      });
  }

  function flyTo(lon, lat, scale) {
    const [x, y] = projection([lon, lat]);
    const transform = d3.zoomIdentity
      .translate(width / 2, height / 2)
      .scale(scale)
      .translate(-x, -y);
    svg.transition().duration(750).ease(d3.easeCubicInOut).call(zoom.transform, transform);
  }

  function flyToBounds(bounds) {
    const [[x0, y0], [x1, y1]] = bounds;
    const dx = x1 - x0, dy = y1 - y0;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const scale = Math.max(1, Math.min(10, 0.8 / Math.max(dx / width, dy / height)));
    const transform = d3.zoomIdentity
      .translate(width / 2, height / 2)
      .scale(scale)
      .translate(-cx, -cy);
    svg.transition().duration(750).ease(d3.easeCubicInOut).call(zoom.transform, transform);
  }

  function closeModal() {
    if (activeModal) activeModal.classList.add("hidden");
    overlay.classList.add("hidden");
    activeModal = null;
    if (activeMarker) {
      activeMarker.classList.remove("active");
      activeMarker = null;
    }
  }

  function openModal(el) {
    if (activeModal) activeModal.classList.add("hidden");
    activeModal = el;
    el.classList.remove("hidden");
    overlay.classList.remove("hidden");
  }

  function showCard(d, node) {
    if (activeMarker) activeMarker.classList.remove("active");
    node.classList.add("active");
    activeMarker = node;

    cardTitle.textContent = d.book;
    cardAuthor.textContent = d.author_display || d.author;
    cardPlace.textContent = [d.region, d.country].filter(Boolean).join(" · ");

    if (d.cover_url) {
      cardCover.src = d.cover_url;
      cardCover.classList.remove("hidden");
      cardCoverFallback.classList.remove("visible");
      cardCover.onerror = () => {
        cardCover.classList.add("hidden");
        cardCoverFallback.textContent = d.book;
        cardCoverFallback.classList.add("visible");
      };
    } else {
      cardCover.classList.add("hidden");
      cardCoverFallback.textContent = d.book;
      cardCoverFallback.classList.add("visible");
    }

    openModal(card);
  }

  document.querySelectorAll("[data-close]").forEach((btn) =>
    btn.addEventListener("click", closeModal)
  );
  document.getElementById("info-btn").addEventListener("click", () => openModal(infoCard));
  overlay.addEventListener("click", closeModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  document.getElementById("zoom-in").addEventListener("click", () => {
    svg.transition().duration(300).call(zoom.scaleBy, 1.5);
  });
  document.getElementById("zoom-out").addEventListener("click", () => {
    svg.transition().duration(300).call(zoom.scaleBy, 1 / 1.5);
  });
  document.getElementById("zoom-reset").addEventListener("click", () => {
    svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
  });

  size();
  window.addEventListener("resize", () => {
    size();
    render();
  });

  let worldData, booksData;

  Promise.all([
    d3.json("assets/world-110m.json"),
    d3.json("data/books.json"),
  ]).then(([world, books]) => {
    worldData = world;
    booksData = books;

    const countries = new Set(books.map((b) => b.country).filter(Boolean));
    counterEl.textContent = `Countries: ${countries.size} · Books: ${books.length}`;

    render();
  });

  function render() {
    if (!worldData) return;

    mapLayer.selectAll("*").remove();
    markersLayer.selectAll("*").remove();

    const land = topojson.feature(worldData, worldData.objects.countries);

    projection = d3.geoNaturalEarth1().fitSize([width, height], land);
    path = d3.geoPath(projection);

    mapLayer.append("path")
      .datum(d3.geoGraticule10())
      .attr("class", "graticule")
      .attr("d", path);

    mapLayer.selectAll("path.land")
      .data(land.features)
      .join("path")
      .attr("class", "land")
      .attr("d", path)
      .on("click", function (event, d) {
        event.stopPropagation();
        flyToBounds(path.bounds(d));
      });

    if (!zoom) setupZoom();

    const groups = markersLayer.selectAll("g.marker-group")
      .data(booksData)
      .join("g")
      .attr("class", "marker-group");

    const iconWrap = groups.append("g")
      .attr("class", "marker-icon pop-in")
      .style("animation-delay", () => `${Math.random() * 0.4}s`)
      .on("click", function (event, d) {
        event.stopPropagation();
        flyTo(d.lon, d.lat, 4);
        showCard(d, this);
      });

    const shape = iconWrap.append("g")
      .attr("transform", `translate(${-ICON_SIZE / 2},${-ICON_SIZE / 2}) scale(${ICON_SIZE / 24})`);

    shape.append("path").attr("class", "book-cover").attr("d", ICON_PATHS.cover);
    shape.append("path").attr("class", "book-spine").attr("d", ICON_PATHS.spine);
    shape.append("path").attr("class", "book-ribbon").attr("d", ICON_PATHS.ribbon);

    positionMarkers();
  }
})();
