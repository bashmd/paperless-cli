use pyo3::prelude::*;

#[pyfunction]
fn normalize_whitespace(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for token in input.split_whitespace() {
        if !out.is_empty() {
            out.push(' ');
        }
        out.push_str(token);
    }
    out
}

#[pymodule]
fn pcli_rust_norm(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(normalize_whitespace, m)?)?;
    Ok(())
}
