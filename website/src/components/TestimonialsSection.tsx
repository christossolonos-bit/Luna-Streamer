import { TESTIMONIALS } from "../data/testimonials";

export function TestimonialsSection() {
  return (
    <section className="testimonials" id="opinions" aria-labelledby="opinions-heading">
      <h2 id="opinions-heading" className="section-title">
        What people are saying
      </h2>
      <p className="testimonials__lead">
        From Discord, Twitch, and YouTube — how the community experiences Luna on stream.
      </p>
      <ul className="testimonials__grid">
        {TESTIMONIALS.map((item) => (
          <li key={`${item.author}-${item.quote.slice(0, 24)}`} className="testimonial-card">
            <blockquote className="testimonial-card__quote">&ldquo;{item.quote}&rdquo;</blockquote>
            <footer className="testimonial-card__footer">
              <cite className="testimonial-card__author">{item.author}</cite>
              {item.source && <span className="testimonial-card__source">{item.source}</span>}
            </footer>
          </li>
        ))}
      </ul>
    </section>
  );
}
