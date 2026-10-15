const form = document.getElementById("search-form");
const input = document.getElementById("query");
const refreshBtn = document.getElementById("refresh");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

const modal = document.getElementById("modal");
const closeBtn = document.getElementById("close-modal");
const narracionEl = document.getElementById("narracion");

function mostrarNarracion(texto) {
  narracionEl.textContent = texto || "";
  narracionEl.hidden = !texto;
}

const threadId = "web-" + Math.random().toString(36).slice(2, 10);
const state = {
  excluir: [],
  ultimaBusqueda: "",
};

function setStatus(texto) {
  statusEl.textContent = texto || "";
}

function filaMeta(pelicula) {
  const partes = [];
  if (pelicula.anio) partes.push(pelicula.anio);
  if (pelicula.nota != null) partes.push("★ " + pelicula.nota);
  return partes.join(" · ");
}

function crearCartel(pelicula) {
  if (pelicula.poster) {
    const img = document.createElement("img");
    img.src = pelicula.poster;
    img.alt = "Cartel de " + pelicula.titulo;
    img.loading = "lazy";
    return img;
  }
  const div = document.createElement("div");
  div.className = "poster-fallback";
  div.textContent = "SIN CARATULA EN VHS";
  return div;
}

function crearTarjeta(pelicula) {
  const card = document.createElement("article");
  card.className = "card";

  const poster = document.createElement("div");
  poster.className = "card-poster";
  poster.appendChild(crearCartel(pelicula));
  if (pelicula.nota != null) {
    const rating = document.createElement("span");
    rating.className = "rating";
    rating.textContent = pelicula.nota;
    poster.appendChild(rating);
  }

  const body = document.createElement("div");
  body.className = "card-body";

  const title = document.createElement("h3");
  title.className = "card-title";
  title.textContent = pelicula.titulo;

  const year = document.createElement("p");
  year.className = "card-year";
  year.textContent = filaMeta(pelicula);

  body.appendChild(title);
  body.appendChild(year);

  card.appendChild(poster);
  card.appendChild(body);
  card.addEventListener("click", () => abrirModal(pelicula));
  return card;
}

function render(lista) {
  resultsEl.innerHTML = "";

  if (!lista.length) {
    const msg = document.createElement("p");
    msg.className = "msg";
    msg.textContent = state.excluir.length
      ? "No hay más resultados en el catálogo para esta búsqueda."
      : "No se encontraron películas. Prueba con un actor, un género o cuéntame tu mood.";
    resultsEl.appendChild(msg);
    refreshBtn.hidden = state.excluir.length === 0;
    return;
  }

  lista.forEach((p) => resultsEl.appendChild(crearTarjeta(p)));
  refreshBtn.hidden = false;
}

function abrirModal(pelicula) {
  document.getElementById("m-title").textContent = pelicula.titulo;

  const poster = document.getElementById("m-poster");
  if (pelicula.poster) {
    poster.src = pelicula.poster;
    poster.alt = "Cartel de " + pelicula.titulo;
    poster.style.display = "block";
  } else {
    poster.removeAttribute("src");
    poster.style.display = "none";
  }

  const meta = document.getElementById("m-meta");
  meta.textContent = filaMeta(pelicula);

  const genres = document.getElementById("m-genres");
  genres.innerHTML = "";
  (pelicula.generos || []).forEach((g) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = g;
    genres.appendChild(chip);
  });

  document.getElementById("m-synopsis").textContent =
    pelicula.sinopsis || "Sin sinopsis disponible.";
  document.getElementById("m-director").textContent =
    pelicula.director || "No disponible";
  document.getElementById("m-cast").textContent =
    (pelicula.reparto || []).join(", ") || "No disponible";
  document.getElementById("m-year").textContent = pelicula.anio || "No disponible";
  document.getElementById("m-runtime").textContent = "Buscando...";
  document.getElementById("m-tagline").textContent = "";
  document.getElementById("m-platforms").textContent =
    (pelicula.plataformas || []).join(", ") || "No disponible en streaming (ES)";

  modal.hidden = false;
  closeBtn.focus();

  // Enriquemos con la ficha en vivo de TMDB (frase, duración, datos frescos).
  cargarFicha(pelicula.tmdb_id);
}

async function cargarFicha(tmdbId) {
  if (!tmdbId) {
    document.getElementById("m-runtime").textContent = "No disponible";
    return;
  }
  try {
    const res = await fetch("/pelicula/" + tmdbId);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const f = await res.json();
    if (f.tagline) document.getElementById("m-tagline").textContent = f.tagline;
    document.getElementById("m-runtime").textContent =
      f.duracion ? f.duracion + " min" : "No disponible";
    if (f.sinopsis) document.getElementById("m-synopsis").textContent = f.sinopsis;
    if (f.director) document.getElementById("m-director").textContent = f.director;
    if (f.reparto && f.reparto.length)
      document.getElementById("m-cast").textContent = f.reparto.join(", ");
    if (f.anio) document.getElementById("m-year").textContent = f.anio;
    if (f.plataformas)
      document.getElementById("m-platforms").textContent =
        f.plataformas.join(", ") || "No disponible en streaming (ES)";
    const genres = document.getElementById("m-genres");
    if (f.generos && f.generos.length) {
      genres.innerHTML = "";
      f.generos.forEach((g) => {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = g;
        genres.appendChild(chip);
      });
    }
  } catch (error) {
    // TMDB no disponible: mantenemos los datos locales ya cargados.
    document.getElementById("m-runtime").textContent = "No disponible";
  }
}

function cerrarModal() {
  modal.hidden = true;
}

async function pedirPeliculas({ nuevaBusqueda }) {
  setStatus("Buscando en el videoclub...");
  refreshBtn.disabled = true;
  mostrarNarracion("");

  const body = {
    mensaje: state.ultimaBusqueda,
    thread_id: threadId,
    excluir_ids: nuevaBusqueda ? [] : state.excluir,
  };

  try {
    const res = await fetch("/recomendar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();

    if (nuevaBusqueda) state.excluir = [];
    data.peliculas.forEach((p) => state.excluir.push(p.id));

    render(data.peliculas);
    mostrarNarracion(data.respuesta);
    if (data.respaldo_mood && data.peliculas.length) {
      setStatus("No encontré títulos exactos para tu mood; te dejo lo mejor valorado del videoclub");
    } else {
      setStatus(
        data.peliculas.length
          ? "Encontradas " + data.peliculas.length + " películas"
          : ""
      );
    }
  } catch (error) {
    state.excluir = nuevaBusqueda ? [] : state.excluir;
    render([]);
    setStatus("Vaya... error de conexión con la API: " + error.message);
  } finally {
    refreshBtn.disabled = false;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const texto = input.value.trim();
  if (!texto) return;
  state.ultimaBusqueda = texto;
  pedirPeliculas({ nuevaBusqueda: true });
});

refreshBtn.addEventListener("click", () => pedirPeliculas({ nuevaBusqueda: false }));

closeBtn.addEventListener("click", cerrarModal);
modal.addEventListener("click", (event) => {
  if (event.target === modal) cerrarModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !modal.hidden) cerrarModal();
});
