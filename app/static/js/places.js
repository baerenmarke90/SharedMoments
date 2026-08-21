(() => {
   const mapState = {
      overview: null,
      detail: null,
      editors: {},
      editorMarkers: {},
   };

   function config() {
      return window.sharedMomentsPlaces || {};
   }

   function leafletAvailable() {
      return typeof window.L !== 'undefined';
   }

   function addTiles(map) {
      const cfg = config();
      window.L.tileLayer(cfg.tileUrl, {
         attribution: cfg.attribution,
         maxZoom: 19,
      }).addTo(map);
   }

   function defaultView(map) {
      const cfg = config();
      map.setView(
         [Number(cfg.defaultLat || 51.1657), Number(cfg.defaultLon || 10.4515)],
         Number(cfg.defaultZoom || 6),
      );
   }

   function showMapFallback(elementId) {
      const element = document.getElementById(elementId);
      if (!element) return;
      element.innerHTML = '';
      const box = document.createElement('div');
      box.className = 'place-map-fallback';
      box.textContent = 'Die Karte konnte nicht geladen werden. Die Ortsliste bleibt vollständig nutzbar.';
      element.appendChild(box);
   }

   function initOverviewMap() {
      const container = document.getElementById('couple-places-map');
      if (!container || mapState.overview) return;
      if (!leafletAvailable()) {
         showMapFallback('couple-places-map');
         return;
      }

      const cfg = config();
      const map = window.L.map(container, {
         scrollWheelZoom: false,
      });
      addTiles(map);
      mapState.overview = map;

      const points = [];
      (cfg.overviewPlaces || []).forEach((place) => {
         const lat = Number(place.latitude);
         const lon = Number(place.longitude);
         if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

         points.push([lat, lon]);
         const marker = window.L.marker([lat, lon]).addTo(map);
         const popup = document.createElement('div');
         const title = document.createElement('strong');
         title.textContent = place.name || 'Ort';
         const meta = document.createElement('div');
         meta.className = 'small';
         meta.textContent = `${Number(place.entry_count || 0)} verknüpfte Inhalte`;
         const link = document.createElement('a');
         link.href = place.url;
         link.textContent = 'Ort ansehen';
         popup.append(title, meta, link);
         marker.bindPopup(popup);
      });

      if (points.length === 1) {
         map.setView(points[0], 12);
      } else if (points.length > 1) {
         map.fitBounds(points, {padding: [35, 35], maxZoom: 13});
      } else {
         defaultView(map);
      }
   }

   function initDetailMap() {
      const container = document.getElementById('couple-place-detail-map');
      if (!container || mapState.detail) return;
      if (!leafletAvailable()) {
         showMapFallback('couple-place-detail-map');
         return;
      }

      const place = config().detailPlace;
      const map = window.L.map(container, {scrollWheelZoom: false});
      addTiles(map);
      mapState.detail = map;

      if (
         place
         && place.latitude !== null
         && place.latitude !== ''
         && place.longitude !== null
         && place.longitude !== ''
         && Number.isFinite(Number(place.latitude))
         && Number.isFinite(Number(place.longitude))
      ) {
         const point = [Number(place.latitude), Number(place.longitude)];
         map.setView(point, 13);
         window.L.marker(point).addTo(map).bindPopup(place.name || 'Ort');
      } else {
         defaultView(map);
      }
   }

   function editorElement(mode, suffix) {
      return document.getElementById(`${mode}-place-${suffix}`);
   }

   function updateCoordinateLabel(mode, lat, lon) {
      const label = editorElement(mode, 'coordinates');
      if (!label) return;
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
         label.textContent = 'Noch keine Kartenposition gesetzt';
         return;
      }
      label.textContent = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
   }

   function setEditorPosition(mode, lat, lon, addressLabel = null) {
      const latitudeInput = editorElement(mode, 'latitude');
      const longitudeInput = editorElement(mode, 'longitude');
      const addressInput = editorElement(mode, 'address');
      if (!latitudeInput || !longitudeInput) return;

      const numericLat = Number(lat);
      const numericLon = Number(lon);
      if (!Number.isFinite(numericLat) || !Number.isFinite(numericLon)) return;

      latitudeInput.value = String(numericLat);
      longitudeInput.value = String(numericLon);
      if (addressInput && addressLabel !== null) addressInput.value = addressLabel;
      updateCoordinateLabel(mode, numericLat, numericLon);

      const map = mapState.editors[mode];
      if (!map || !leafletAvailable()) return;

      if (mapState.editorMarkers[mode]) {
         mapState.editorMarkers[mode].setLatLng([numericLat, numericLon]);
      } else {
         mapState.editorMarkers[mode] = window.L.marker(
            [numericLat, numericLon],
            {draggable: true},
         ).addTo(map);

         mapState.editorMarkers[mode].on('dragend', (event) => {
            const point = event.target.getLatLng();
            setEditorPosition(mode, point.lat, point.lng, '');
         });
      }

      map.setView([numericLat, numericLon], Math.max(map.getZoom(), 12));
   }

   function initEditorMap(mode) {
      const container = editorElement(mode, 'map');
      if (!container) return;
      if (!leafletAvailable()) {
         showMapFallback(`${mode}-place-map`);
         return;
      }

      let map = mapState.editors[mode];
      if (!map) {
         map = window.L.map(container, {scrollWheelZoom: false});
         addTiles(map);
         mapState.editors[mode] = map;
         defaultView(map);

         map.on('click', (event) => {
            setEditorPosition(mode, event.latlng.lat, event.latlng.lng, '');
         });

         const latRaw = editorElement(mode, 'latitude')?.value ?? '';
         const lonRaw = editorElement(mode, 'longitude')?.value ?? '';
         const lat = Number(latRaw);
         const lon = Number(lonRaw);
         if (
            latRaw !== ''
            && lonRaw !== ''
            && Number.isFinite(lat)
            && Number.isFinite(lon)
         ) {
            setEditorPosition(mode, lat, lon);
         } else {
            updateCoordinateLabel(mode, NaN, NaN);
         }
      }

      window.setTimeout(() => map.invalidateSize(), 100);
   }

   function openDialogAndMap(dialogSelector, mode) {
      if (typeof window.callUi === 'function') {
         window.callUi(dialogSelector);
      }
      window.setTimeout(() => initEditorMap(mode), 80);
   }

   window.openPlaceCreateDialog = () => {
      openDialogAndMap('#dialog-create-place', 'create');
   };

   window.openPlaceEditDialog = () => {
      openDialogAndMap('#dialog-edit-place', 'edit');
   };

   window.searchPlaceLocation = async (mode) => {
      const queryInput = editorElement(mode, 'search');
      const results = editorElement(mode, 'results');
      if (!queryInput || !results) return;

      const query = String(queryInput.value || '').trim();
      if (query.length < 2) {
         results.textContent = 'Bitte mindestens zwei Zeichen eingeben.';
         return;
      }

      results.innerHTML = '';
      const loading = document.createElement('div');
      loading.className = 'small place-search-message';
      loading.textContent = 'Suche …';
      results.appendChild(loading);

      try {
         const endpoint = config().geocodeUrl || '/places/geocode';
         const response = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`);
         const payload = await response.json();
         results.innerHTML = '';

         if (!response.ok || payload.status !== 'success') {
            throw new Error(payload.message || 'Geocoding failed');
         }

         if (!payload.results || payload.results.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'small place-search-message';
            empty.textContent = 'Kein passender Ort gefunden.';
            results.appendChild(empty);
            return;
         }

         payload.results.forEach((result) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'place-search-result';
            const icon = document.createElement('i');
            icon.textContent = 'location_on';
            const text = document.createElement('span');
            text.textContent = result.label;
            button.append(icon, text);
            button.addEventListener('click', () => {
               setEditorPosition(mode, result.lat, result.lon, result.label);
               results.innerHTML = '';
            });
            results.appendChild(button);
         });
      } catch (error) {
         results.innerHTML = '';
         const failed = document.createElement('div');
         failed.className = 'small place-search-message';
         failed.textContent = 'Ortssuche nicht verfügbar. Du kannst die Position auch direkt auf der Karte antippen.';
         results.appendChild(failed);
      }
   };

   window.useCurrentPlaceLocation = (mode) => {
      if (!navigator.geolocation) return;
      navigator.geolocation.getCurrentPosition(
         (position) => {
            setEditorPosition(
               mode,
               position.coords.latitude,
               position.coords.longitude,
               'Aktueller Standort',
            );
         },
         () => {
            const results = editorElement(mode, 'results');
            if (results) {
               results.textContent = 'Der aktuelle Standort konnte nicht ermittelt werden.';
            }
         },
         {enableHighAccuracy: true, timeout: 8000},
      );
   };

   window.filterPlaceCards = (value) => {
      const needle = String(value || '').trim().toLocaleLowerCase();
      document.querySelectorAll('[data-place-card]').forEach((card) => {
         const haystack = String(card.dataset.search || '');
         card.style.display = (!needle || haystack.includes(needle)) ? '' : 'none';
      });
   };

   window.filterPlaceCandidates = (value) => {
      const needle = String(value || '').trim().toLocaleLowerCase();
      document.querySelectorAll('[data-place-candidate]').forEach((candidate) => {
         const haystack = String(candidate.dataset.search || '');
         candidate.style.display = (!needle || haystack.includes(needle)) ? '' : 'none';
      });

      document.querySelectorAll('[data-place-candidate-group]').forEach((group) => {
         const hasVisible = Array.from(
            group.querySelectorAll('[data-place-candidate]'),
         ).some((candidate) => candidate.style.display !== 'none');
         group.style.display = hasVisible ? '' : 'none';
      });
   };

   document.addEventListener('DOMContentLoaded', () => {
      initOverviewMap();
      initDetailMap();

      if (config().autoOpenCreate) {
         window.openPlaceCreateDialog();
      }
   });
})();
