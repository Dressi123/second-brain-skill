APPROVAL_PAGE = """<!DOCTYPE html>
<html>
<head><title>Second Brain -- Authorize</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, sans-serif; background: #F0EEE6; color: #262521;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  form {{ background: #fff; padding: 2rem; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
          width: 300px; }}
  h1 {{ font-size: 1.1rem; margin: 0 0 0.5rem; }}
  p {{ font-size: 0.85rem; color: #87867F; margin: 0 0 1.5rem; }}
  input {{ width: 100%; padding: 0.6rem; border: 1px solid #E4DFD1; border-radius: 8px;
           box-sizing: border-box; font-size: 1rem; margin-bottom: 1rem; }}
  button {{ width: 100%; padding: 0.7rem; border: none; border-radius: 8px; background: #CC785C;
            color: #fff; font-size: 1rem; cursor: pointer; }}
  .error {{ color: #C1584A; font-size: 0.85rem; margin-top: -0.75rem; margin-bottom: 1rem; }}
</style>
</head>
<body>
  <form method="POST">
    <h1>Authorize access to Second Brain</h1>
    <p>{client_name} is requesting read access to your vault.</p>
    {error_html}
    <input type="password" name="password" placeholder="Password" autofocus required>
    <button type="submit">Approve</button>
  </form>
</body>
</html>"""
