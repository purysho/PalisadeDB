from __future__ import annotations
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from palisade import Database, DatabaseError, SQLError

BG='#0f1318'; PANEL='#171d24'; PANEL2='#1d252e'; FG='#edf2f7'; MUTED='#98a2ad'; ACCENT='#c9f45b'; BORDER='#2b3541'

def style_app(root):
    root.configure(bg=BG)
    s=ttk.Style(root)
    try:s.theme_use('clam')
    except tk.TclError:pass
    s.configure('.',background=BG,foreground=FG,fieldbackground=PANEL,font=('Segoe UI',10))
    s.configure('TFrame',background=BG); s.configure('Panel.TFrame',background=PANEL)
    s.configure('TLabel',background=BG,foreground=FG); s.configure('Muted.TLabel',background=BG,foreground=MUTED)
    s.configure('Title.TLabel',background=BG,foreground=FG,font=('Segoe UI Semibold',20))
    s.configure('CardLabel.TLabel',background=PANEL,foreground=MUTED,font=('Segoe UI',9))
    s.configure('TButton',background=PANEL2,foreground=FG,padding=(10,7),bordercolor=BORDER)
    s.map('TButton',background=[('active','#26313c')])
    s.configure('Accent.TButton',background=ACCENT,foreground='#111417',padding=(11,7),font=('Segoe UI Semibold',10))
    s.map('Accent.TButton',background=[('active','#d8ff78')])
    s.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=FG,bordercolor=BORDER,rowheight=28)
    s.configure('Treeview.Heading',background=PANEL2,foreground=FG,font=('Segoe UI Semibold',9),relief='flat')
    s.map('Treeview',background=[('selected','#2b3b48')])
    s.configure('TNotebook',background=BG,borderwidth=0); s.configure('TNotebook.Tab',background=PANEL,foreground=MUTED,padding=(13,8))
    s.map('TNotebook.Tab',background=[('selected',PANEL2)],foreground=[('selected',FG)])

class App:
    def __init__(self,root):
        self.root=root; style_app(root)
        root.title('PalisadeDB — Database Workbench'); root.geometry('1200x780'); root.minsize(900,620)
        self.db=None; self.path=None; self.status=tk.StringVar(value='Open or create a .pdb database.')
        self.build_ui()

    def build_ui(self):
        top=ttk.Frame(self.root,padding=(22,18,22,8)); top.pack(fill='x')
        ttk.Label(top,text='PalisadeDB',style='Title.TLabel').pack(side='left')
        ttk.Label(top,text='Database workbench',style='Muted.TLabel').pack(side='left',padx=(14,0),pady=(6,0))
        ttk.Button(top,text='New Database',command=self.new_db).pack(side='right')
        ttk.Button(top,text='Open Database',command=self.open_db).pack(side='right',padx=(0,8))

        row=ttk.Frame(self.root,padding=(22,2,22,10)); row.pack(fill='x')
        self.path_label=ttk.Label(row,text='No database open',style='Muted.TLabel'); self.path_label.pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Refresh Inspectors',command=self.refresh_all).pack(side='right')

        paned=ttk.Panedwindow(self.root,orient='horizontal'); paned.pack(fill='both',expand=True,padx=22,pady=(0,10))
        left=ttk.Frame(paned,style='Panel.TFrame',padding=10); paned.add(left,weight=1)
        ttk.Label(left,text='TABLES',style='CardLabel.TLabel').pack(anchor='w',pady=(0,7))
        self.tables=tk.Listbox(left,bg=PANEL,fg=FG,selectbackground='#2b3b48',selectforeground=FG,relief='flat',highlightthickness=0,font=('Segoe UI',10))
        self.tables.pack(fill='both',expand=True); self.tables.bind('<<ListboxSelect>>',self.table_selected); self.tables.bind('<Double-1>',self.query_selected_table)

        right=ttk.Frame(paned); paned.add(right,weight=5)
        self.nb=ttk.Notebook(right); self.nb.pack(fill='both',expand=True)
        self.build_sql_tab(); self.schema=self.text_tab('Schema'); self.btree=self.text_tab('B+ Tree'); self.build_pages_tab(); self.stats=self.text_tab('Stats / WAL'); self.integrity=self.text_tab('Integrity')

        foot=ttk.Frame(self.root,padding=(22,5,22,14)); foot.pack(fill='x')
        ttk.Label(foot,textvariable=self.status,style='Muted.TLabel').pack(side='left')

    def text_tab(self,title):
        f=ttk.Frame(self.nb); self.nb.add(f,text=title)
        t=tk.Text(f,bg=PANEL,fg=FG,insertbackground=FG,relief='flat',font=('Consolas',10),wrap='none',padx=12,pady=10)
        t.pack(fill='both',expand=True); t.configure(state='disabled'); return t

    def build_sql_tab(self):
        f=ttk.Frame(self.nb); self.nb.add(f,text='SQL')
        bar=ttk.Frame(f); bar.pack(fill='x',pady=(0,7))
        ttk.Button(bar,text='Run  Ctrl+Enter',style='Accent.TButton',command=self.run_sql).pack(side='left')
        ttk.Button(bar,text='Clear',command=lambda:self.sql.delete('1.0','end')).pack(side='left',padx=(7,0))
        self.sql=tk.Text(f,height=7,bg=PANEL,fg=FG,insertbackground=FG,relief='flat',font=('Consolas',11),padx=12,pady=10)
        self.sql.pack(fill='x'); self.sql.bind('<Control-Return>',lambda e:(self.run_sql(),'break')[1])
        self.sql.insert('1.0','SELECT * FROM users;')
        rf=ttk.Frame(f); rf.pack(fill='both',expand=True,pady=(8,0))
        self.results=ttk.Treeview(rf,show='headings'); self.results.pack(side='left',fill='both',expand=True)
        sy=ttk.Scrollbar(rf,orient='vertical',command=self.results.yview); sy.pack(side='right',fill='y'); self.results.configure(yscrollcommand=sy.set)

    def build_pages_tab(self):
        f=ttk.Frame(self.nb); self.nb.add(f,text='Pages')
        self.pages=ttk.Treeview(f,columns=('page','type'),show='headings'); self.pages.heading('page',text='Page'); self.pages.heading('type',text='Type')
        self.pages.column('page',width=90,anchor='center'); self.pages.column('type',width=300,anchor='w'); self.pages.pack(fill='both',expand=True)

    def set_text(self,w,text):
        w.configure(state='normal'); w.delete('1.0','end'); w.insert('1.0',text); w.configure(state='disabled')

    def new_db(self):
        p=filedialog.asksaveasfilename(title='Create PalisadeDB database',defaultextension='.pdb',filetypes=[('PalisadeDB','*.pdb'),('All files','*.*')])
        if p:self.load_db(Path(p))

    def open_db(self):
        p=filedialog.askopenfilename(title='Open PalisadeDB database',filetypes=[('PalisadeDB','*.pdb'),('All files','*.*')])
        if p:self.load_db(Path(p))

    def load_db(self,p):
        try:
            self.db=Database(p); self.path=Path(p); self.path_label.configure(text=str(self.path)); self.status.set('Database ready.'); self.refresh_all()
            r=self.db.pager.recovery
            if r.recovered:self.status.set(f'Recovered WAL tx {r.txid}: {r.pages_replayed} page(s) replayed.')
        except Exception as e:messagebox.showerror('PalisadeDB',str(e))

    def require_db(self):
        if self.db:return True
        messagebox.showinfo('PalisadeDB','Open or create a database first.'); return False

    def run_sql(self):
        if not self.require_db():return
        sql=self.sql.get('1.0','end').strip()
        if not sql:return
        try:
            r=self.db.execute(sql)
            if r['kind']=='rows':self.show_rows(r['rows']);self.status.set(f"{len(r['rows'])} row(s).")
            else:self.show_rows([]);self.status.set(r['message'])
            self.refresh_all()
        except (DatabaseError,SQLError,ValueError,Exception) as e:messagebox.showerror('PalisadeDB',str(e));self.status.set('SQL error.')

    def show_rows(self,rows):
        self.results.delete(*self.results.get_children()); cols=list(rows[0]) if rows else []; self.results['columns']=cols
        for c in cols:self.results.heading(c,text=c);self.results.column(c,width=max(110,min(320,70+len(c)*14)),anchor='w')
        for r in rows:self.results.insert('', 'end',values=[r.get(c,'') for c in cols])

    def selected_table(self):
        s=self.tables.curselection(); return self.tables.get(s[0]) if s else None

    def table_selected(self,_=None):
        n=self.selected_table()
        if n:self.refresh_table(n)

    def query_selected_table(self,_=None):
        n=self.selected_table()
        if n:self.sql.delete('1.0','end');self.sql.insert('1.0',f'SELECT * FROM {n};');self.nb.select(0);self.run_sql()

    def refresh_table(self,name):
        try:
            self.set_text(self.schema,self.db.schema(name))
            d=self.db.btree(name); lines=[f"root={d['root']}  height={d['height']}  pages={d['pages']}"]
            for depth,level in enumerate(d['levels']):
                lines.append(f'\nLEVEL {depth}')
                for node in level:
                    if node['type']=='leaf':lines.append(f"  page {node['page']:>4} LEAF keys={node['keys'][:30]} next={node['next']}")
                    else:lines.append(f"  page {node['page']:>4} INTERNAL seps={node['keys'][:30]} children={node['children'][:31]}")
            self.set_text(self.btree,'\n'.join(lines))
        except Exception as e:self.set_text(self.schema,str(e));self.set_text(self.btree,str(e))

    def refresh_all(self):
        if not self.db:return
        old=self.selected_table(); names=self.db.tables(); self.tables.delete(0,'end')
        for n in names:self.tables.insert('end',n)
        if names:
            target=old if old in names else names[0]; i=names.index(target); self.tables.selection_set(i); self.tables.activate(i); self.refresh_table(target)
        self.pages.delete(*self.pages.get_children())
        for p in self.db.pages():self.pages.insert('', 'end',values=(p['page'],p['type']))
        self.set_text(self.stats,json.dumps(self.db.stats(),indent=2,default=str))
        issues=self.db.integrity_check(); self.set_text(self.integrity,'OK — no integrity issues found.' if not issues else 'INTEGRITY ISSUES\n\n'+'\n'.join('• '+x for x in issues))

def main():
    root=tk.Tk(); App(root); root.mainloop()
if __name__=='__main__':main()
