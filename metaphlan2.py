#!/usr/bin/env python

from __future__ import with_statement 

# ==============================================================================
# MetaPhlAn v2.x: METAgenomic PHyLogenetic ANalysis for taxonomic classification 
#                 of metagenomic data
#
# Authors: Nicola Segata (nicola.segata@unitn.it)
#
# Please type "./metaphlan2.py -h" for usage help
#
# ==============================================================================

__author__ = 'Nicola Segata (nicola.segata@unitn.it)'
__version__ = '2.0.0 alpha'
__date__ = '1 April 2014'


import sys
import os

try:
    import numpy as np 
except ImportError:
    sys.stderr.write("Error! numpy python library not detected!!\n")
    sys.exit()
import tempfile as tf
import argparse as ap
import subprocess as subp
import multiprocessing as mp
from collections import defaultdict as defdict
import bz2 
try:
    import cPickle as pickle
except:
    import pickle

#*************************************************************
#*  Imports related to biom file generation                  *
#*************************************************************
try:
    from biom.table import  * 
except ImportError:
    sys.stderr.write("Warning! Biom python library not detected! Exporting to biom format will not work!\n")
try:
    import json
except ImportError:
    sys.stderr.write("Warning! json python library not detected! Exporting to biom format will not work!\n")
from numpy import array
#*************************************************************
#*  End imports related to biom file generation              *
#*************************************************************

# This set contains the markers that after careful validation are found to have low precision or recall
# We esclude the markers here to avoid generating a new marker DB when changing just few markers
markers_to_exclude = set(['NC_001782.1'])

tax_units = "kpcofgst"

def read_params(args):
    p = ap.ArgumentParser( description= 
            "DESCRIPTION\n"
            " MetaPhlAn version "+__version__+" ("+__date__+"): METAgenomic PHyLogenetic ANalysis for\n"
            " taxonomic classification of metagenomic reads.\n\n"
            "AUTHORS: "+__author__+"\n\n"
            "COMMON COMMANDS\n\n"
            "* Profiling a metagenome from raw reads (requires BowTie2 in the system path \n"
            "  with execution and read permissions, Perl installed, and the BowTie2 marker DB \n"
            "  provided with MetaPhlAn):\n"
            "metaphlan.py metagenome.fasta --mpa_pkl mpa.pkl --bowtie2db bowtie2db/mpa\n"
            "  mpa.pkl is the marker metadata file provided with the MetaPhlAn package\n\n"
            "* When possible, it is recommended to use fastq files for higher accuracy: \n"
            "metaphlan.py metagenome.fastq --mpa_pkl mpa.pkl --bowtie2db bowtie2db/mpa --bt2_ps sensitive-local\n\n"
            "* you can take advantage of multiple CPUs and you can save the intermediate BowTie2\n"
            "  output\n for re-running MetaPhlAn extremely quickly:\n"
            "metaphlan.py metagenome.fastq --mpa_pkl mpa.pkl --bowtie2db bowtie2db/mpa --nproc 5 --bowtie2out metagenome.bt2out.txt\n\n"
            "* if you already mapped your metagenome against the marker DB (using a previous \n"
            "  MetaPhlAn run, you can obtain the results in few seconds:\n"
            "metaphlan.py --input_type bowtie2out --mpa_pkl mpa.pkl metagenome.bowtie2out.txt\n"
            "  (notice that 'bowtie2out' is a reduced SAM file that can be obtained from \n"
            "  a standard SAM file as follows: \n"
            "cat file.sam | cut -f 1,3 | grep -v \"*\" > file.bowtie2out.txt\n\n"
            "* The metagenome can also be passed from the standard input but \n"
            "  it is necessary to specify the input format explicitly:\n"
            "tar xjf metagenome.tar.bz2 --to-stdout | metaphlan.py --mpa_pkl mpa.pkl --input_type multifastq --blastdb blastdb/mpa\n\n"
            "* Also the pre-computed BowTie2 output can be provided with a pipe (again \n"
            "  specifying the input type): \n"
            "metaphlan.py --input_type bowtie2out --mpa_pkl mpa.pkl < metagenome.bowtie2out.txt > profiling_output.txt\n\n"
            "* you can also set advanced options for the BowTie2 step selecting the preset option \n"
            "  among 'sensitive','very-sensitive','sensitive-local','very-sensitive-local' \n"
            "  (valid for metagenome as input only):\n" 
            "metaphlan.py --bt2_ps very-sensitive-local --mpa_pkl mpa.pkl metagenome.fasta\n\n",
            formatter_class=ap.RawTextHelpFormatter )
    arg = p.add_argument

    arg( 'inp', metavar='INPUT_FILE', type=str, nargs='?', default=None, help= 
         "the input file can be:\n"
         "* a multi-fasta file containing metagenomic reads\n"
         "OR\n"
         "* a NCBI BLAST output file (-outfmt 6 format) of the metagenome against the MetaPhlAn database. \n"
         "OR\n"
         "* a BowTie2 output file of the metagenome generated by a previous MetaPhlAn run \n"
         "The software will recognize the format automatically.\n"
         "If the input file is missing, the script assumes that the input is provided using the standard \n"
         "input, and the input format has to be specified with --input_type" )   
    
    arg( 'output', metavar='OUTPUT_FILE', type=str, nargs='?', default=None,
         help= "the tab-separated output file of the predicted taxon relative "
               "abundances \n"
               "[stdout if not present]")

    arg( '-v','--version', action='version', version="MetaPhlAn version "+__version__+"\t("+__date__+")",
         help="Prints the current MetaPhlAn version and exit\n" )

    arg( '--mpa_pkl', metavar="", default=None, type=str, # !!!!
         help = "the metadata pickled MetaPhlAn file")
    
    stat_choices = ['avg_g','avg_l','tavg_g','tavg_l','wavg_g','wavg_l','med']
    arg( '--stat', metavar="", choices=stat_choices, default="tavg_g", type=str, help = 
         "EXPERIMENTAL! Statistical approach for converting marker abundances into clade abundances\n"
         "'avg_g'  : clade global (i.e. normalizing all markers together) average\n"
         "'avg_l'  : average of length-normalized marker counts\n"
         "'tavg_g' : truncated clade global average at --stat_q quantile\n"
         "'tavg_l' : trunated average of length-normalized marker counts (at --stat_q)\n"
         "'wavg_g' : winsorized clade global average (at --stat_q)\n"
         "'wavg_l' : winsorized average of length-normalized marker counts (at --stat_q)\n"
         "'med'    : median of length-normalized marker counts\n"
         "[default tavg_g]"   ) 
    
    analysis_types = ['rel_ab', 'reads_map', 'clade_profiles', 'marker_ab_table', 'marker_pres_table']
    arg( '-t', metavar='ANALYSIS TYPE', type=str, choices = analysis_types, 
         default='rel_ab', help = 
         "Type of analysis to perform: \n"
         " * rel_ab: profiling a metagenomes in terms of relative abundances\n"
         " * reads_map: mapping from reads to clades (only reads hitting a marker)\n"
         " * clade_profiles: normalized marker counts for clades with at least a non-null marker\n"
         " * marker_ab_table: normalized marker counts (only when > 0.0 and normalized by metagenome size if --nreads is specified)\n"
         " * marker_pres_table: list of markers present in the sample (threshold at 1.0 if not differently specified with --pres_th\n"
         "[default 'rel_ab']" )

    arg( '--tax_lev', metavar='TAXONOMIC_LEVEL', type=str, 
         choices='a'+tax_units, default='a', help = 
         "The taxonomic level for the relative abundance output:\n"
         "'a' : all taxonomic levels\n"
         "'k' : kingdoms (Bacteria and Archaea) only\n"
         "'p' : phyla only\n"
         "'c' : classes only\n"
         "'o' : orders only\n"
         "'f' : families only\n"
         "'g' : genera only\n"
         "'s' : species only\n"
         "[default 'a']" )
    
    arg( '--nreads', metavar="NUMBER_OF_READS", type=int, default = None, help =
         "The total number of reads in the original metagenome. It is used only when \n"
         "-t marker_table is specified for normalizing the length-normalized counts \n"
         "with the metagenome size as well. No normalization applied if --nreads is not \n"
         "specified" )

    arg( '--pres_th', metavar="PRESENCE_THRESHOLD", type=int, default = 1.0, help =
         'Threshold for calling a marker present by the -t marker_pres_table option' )

    arg( '--bowtie2db', metavar="METAPHLAN_BOWTIE2_DB", type=str, default = None,
         help = "The BowTie2 database file of the MetaPhlAn database " )

    bt2ps = ['sensitive','very-sensitive','sensitive-local','very-sensitive-local']
    arg( '--bt2_ps', metavar="BowTie2 presets", default='very-sensitive', choices=bt2ps,
         help = "presets options for BowTie2 (applied only when a multifasta file is provided)\n"
                "The choices enabled in MetaPhlAn are:\n"
                " * sensitive\n"
                " * very-sensitive\n"
                " * sensitive-local\n"
                " * very-sensitive-local\n"
                "[default very-sensitive]\n"   )
    
    arg( '--tmp_dir', metavar="", default=None, type=str, help = 
         "the folder used to store temporary files \n"
         "[default is the OS dependent tmp dir]\n"   )
    
    arg( '--min_cu_len', metavar="", default="2000", type=int, help =
         "minimum total nucleotide length for the markers in a clade for\n"
         "estimating the abundance without considering sub-clade abundances\n"
         "[default 2000]\n"   )

    input_type_choices = ['automatic','multifasta','multifastq','bowtie2out','sam'] # !!!!
    arg( '--input_type', choices=input_type_choices, default = 'automatic', help =  
         "set wheter the input is the multifasta file of metagenomic reads or \n"
         "the blast output (outfmt 6 format) of the reads against the MetaPhlAn db.\n"
         "[default 'automatic', i.e. the script will try to guess the input format]\n" )

    arg( '--ignore_viruses', action='store_true', help=
         "Do not profile viral organisms" )
    arg( '--ignore_eukaryotes', action='store_true', help=
         "Do not profile eukaryotic organisms" )
    arg( '--ignore_bacteria', action='store_true', help=
         "Do not profile bacterial organisms" )
    arg( '--ignore_archaea', action='store_true', help=
         "Do not profile archeal organisms" )

    arg( '--stat_q', metavar="", type = float, default=0.1, help = 
         "Quantile value for the robust average\n"
         "[default 0.1]"   )

    arg( '--avoid_disqm', action="store_true", help = 
         "Descrivate the procedure of disambiguating the quasi-markers based on the \n"
         "marker abundance pattern found in the sample. It is generally recommended \n"
         "too keep the disambiguation procedure in order to minimize false positives\n")

    arg( '--bowtie2_exe', type=str, default = None, help =
         'Full path and name of the BowTie2 executable. This option allows \n'
         'MetaPhlAn to reach the executable even when it is not in the system \n'
         'PATH or the system PATH is unreachable\n' )

    arg( '--bowtie2out', metavar="FILE_NAME", type=str, default = None, help = 
         "The file for saving the output of BowTie2\n" )
    arg( '--no_map', action='store_true', help=
         "Avoid storing the --bowtie2out map file\n" )

    arg( '-o', '--output_file',  metavar="output file", type=str, default=None, help = 
         "The output file (if not specified as positional argument)\n")

    arg( '--nproc', metavar="N", type=int, default=1, help = 
         "The number of CPUs to use for parallelizing the blasting\n"
         "[default 1, i.e. no parallelism]\n" ) 

    #*************************************************************
    #* Parameters related to biom file generation                *
    #*************************************************************         
    arg( '--biom', '--biom_output_file',  metavar="biom_output", type=str, default=None, help = 
         "If requesting biom file output: The name of the output file in biom format \n")

    arg( '--mdelim', '--metadata_delimiter_char',  metavar="mdelim", type=str, default="|", help = 
         "Delimiter for bug metadata: - defaults to pipe. e.g. the pipe in k__Bacteria|p__Proteobacteria \n")
    #*************************************************************
    #* End parameters related to biom file generation            *
    #*************************************************************    

    return vars(p.parse_args()) 

def run_bowtie2(  fna_in, outfmt6_out, bowtie2_db, preset, nproc, file_format = "multifasta", exe = None ):
    try:
        if not fna_in:
            fna_in = "-"
        bowtie2_cmd = [ exe if exe else 'bowtie2', 
                        "--quiet", "--sam-no-hd", "--sam-no-sq","--no-unal", 
                        "--"+preset, 
                        "-x", bowtie2_db,
                        "-U", fna_in,
                         ] + ([] if int(nproc) < 2 else ["-p",str(nproc)])
        bowtie2_cmd += (["-f"] if file_format == "multifasta" else []) 
        p = subp.Popen( bowtie2_cmd, stdout=subp.PIPE )
        outf = bz2.BZ2File(outfmt6_out, "w") if outfmt6_out.endswith(".bz2") else open( outfmt6_out, "w" )
        for o in (l.strip().split('\t') for l in p.stdout):
            if o[2][-1] != '*':
                outf.write( "\t".join([o[0],o[2]]) +"\n" )
        outf.close()
    
    except OSError:
        sys.stderr.write( "OSError: fatal error running BowTie2. Is BowTie2 in the system path?\n" )
        sys.exit(1)
    except ValueError:
        sys.stderr.write( "ValueError: fatal error running BowTie2.\n" )
        sys.exit(1)
    except IOError:
        sys.stderr.write( "IOError: fatal error running BowTie2.\n" )
        sys.exit(1)
    if p.returncode == 13:
        sys.stderr.write( "Permission Denied Error: fatal error running BowTie2." 
          "Is the BowTie2 file in the path with execution and read permissions?\n" )
        sys.exit(1)

def guess_input_format( inp_file ):
    with open( inp_file ) as inpf:
        for i,l in enumerate(inpf):
            line = l.strip()
            if line[0] == '#': continue
            if line[0] == '>': return 'multifasta'
            if line[0] == '@': return 'multifastq'
            if len(l.split('\t')) == 2: return 'bowtie2out'
            if i > 20: break
    return None

class TaxClade:
    min_cu_len = -1
    markers2lens = None
    stat = None
    quantile = None
    avoid_disqm = False

    def __init__( self, name, uncl = False ):
        self.children, self.markers2nreads = {}, {}
        self.name, self.father = name, None
        self.uncl, self.subcl_uncl = uncl, False
        self.abundance, self.uncl_abundance = None, 0 

    def add_child( self, name ):
        new_clade = TaxClade( name )
        self.children[name] = new_clade
        new_clade.father = self
        return new_clade

    
    def get_terminals( self ):
        terms = []
        if not self.children:
            return [self]
        for c in self.children.values():
            terms += c.get_terminals()
        return terms


    def get_full_name( self ):
        fullname = [self.name]
        cl = self.father
        while cl:
            fullname = [cl.name] + fullname
            cl = cl.father
        return "|".join(fullname[1:])

    def get_normalized_counts( self ):
        return [(m,float(n)*1000.0/self.markers2lens[m]) 
                    for m,n in self.markers2nreads.items()]

    def compute_abundance( self ):
        if self.abundance is not None: return self.abundance
        sum_ab = sum([c.compute_abundance() for c in self.children.values()]) 
        rat_nreads = sorted([(self.markers2lens[m],n) 
                                    for m,n in self.markers2nreads.items()],
                                            key = lambda x: x[1])

        rat_nreads, removed = [], []
        for m,n in self.markers2nreads.items():
            misidentified = False

            if not self.avoid_disqm:
                for e in self.markers2exts[m]:
                    toclade = self.taxa2clades[e]
                    m2nr = toclade.markers2nreads
                    tocladetmp = toclade
                    while len(tocladetmp.children) == 1:
                        tocladetmp = list(tocladetmp.children.values())[0]
                        m2nr = tocladetmp.markers2nreads
    
                    nonzeros = sum([v>0 for v in m2nr.values()])
                    if len(m2nr):
                        if float(nonzeros) / len(m2nr) > 0.33:
                            misidentified = True
                            removed.append( (self.markers2lens[m],n) )
                            break
            if not misidentified:
                rat_nreads.append( (self.markers2lens[m],n) ) 
       
        if not self.avoid_disqm and len(removed):
            n_rat_nreads = float(len(rat_nreads))
            n_removed = float(len(removed))
            n_tot = n_rat_nreads + n_removed
            n_ripr = 10
            
            if len(self.get_terminals()) < 2:
                n_ripr = 0

            if "k__Viruses" in self.get_full_name():
                n_ripr = 0

            if n_rat_nreads < n_ripr and n_tot > n_rat_nreads:
                rat_nreads += removed[:n_ripr-int(n_rat_nreads)]

        
        rat_nreads = sorted(rat_nreads, key = lambda x: x[1])

        rat_v,nreads_v = zip(*rat_nreads) if rat_nreads else ([],[])
        rat, nrawreads, loc_ab = float(sum(rat_v)) or -1.0, sum(nreads_v), 0.0
        quant = int(self.quantile*len(rat_nreads))
        ql,qr,qn = (quant,-quant,quant) if quant else (None,None,0)
     
        if self.name[0] == 't' and (len(self.father.children) > 1 or "_sp" in self.father.name or "k__Viruses" in self.get_full_name()):
            non_zeros = float(len([n for r,n in rat_nreads if n > 0])) 
            nreads = float(len(rat_nreads))
            if nreads == 0.0 or non_zeros / nreads < 0.7:
                self.abundance = 0.0
                return 0.0

        if rat < 0.0:
            pass
        elif self.stat == 'avg_g' or (not qn and self.stat in ['wavg_g','tavg_g']):
            loc_ab = nrawreads / rat if rat >= 0 else 0.0
        elif self.stat == 'avg_l' or (not qn and self.stat in ['wavg_l','tavg_l']):
            loc_ab = np.mean([float(n)/r for r,n in rat_nreads]) 
        elif self.stat == 'tavg_g':
            wnreads = sorted([(float(n)/r,r,n) for r,n in rat_nreads], key=lambda x:x[0])
            den,num = zip(*[v[1:] for v in wnreads[ql:qr]])
            loc_ab = float(sum(num))/float(sum(den)) if any(den) else 0.0
        elif self.stat == 'tavg_l':
            loc_ab = np.mean(sorted([float(n)/r for r,n in rat_nreads])[ql:qr])
        elif self.stat == 'wavg_g':
            vmin, vmax = nreads_v[ql], nreads_v[qr]
            wnreads = [vmin]*qn+list(nreads_v[ql:qr])+[vmax]*qn
            loc_ab = float(sum(wnreads)) / rat  
        elif self.stat == 'wavg_l':
            wnreads = sorted([float(n)/r for r,n in rat_nreads])
            vmin, vmax = wnreads[ql], wnreads[qr]
            wnreads = [vmin]*qn+list(wnreads[ql:qr])+[vmax]*qn
            loc_ab = np.mean(wnreads) 
        elif self.stat == 'med':
            loc_ab = np.median(sorted([float(n)/r for r,n in rat_nreads])[ql:qr]) 
        
        self.abundance = loc_ab
        if rat < self.min_cu_len and self.children:
            self.abundance = sum_ab
        elif loc_ab < sum_ab:
            self.abundance = sum_ab

        if self.abundance > sum_ab and self.children: # *1.1??
            self.uncl_abundance = self.abundance - sum_ab
        self.subcl_uncl = not self.children and self.name[0] not in tax_units[-2:] 

        return self.abundance

    def get_all_abundances( self ):
        ret = [(self.name,self.abundance)]
        if self.uncl_abundance > 0.0:
            lchild = list(self.children.values())[0].name[:3]
            ret += [(lchild+self.name[3:]+"_unclassified",self.uncl_abundance)]
        if self.subcl_uncl and self.name[0] != tax_units[-2]:
            cind = tax_units.index( self.name[0] )
            ret += [(   tax_units[cind+1]+self.name[1:]+"_unclassified",
                        self.abundance)]
        for c in self.children.values():
            ret += c.get_all_abundances()
        return ret


class TaxTree:
    def __init__( self, mpa ): #, min_cu_len ):
        self.root = TaxClade( "root" )
        self.all_clades, self.markers2lens, self.markers2clades, self.taxa2clades, self.markers2exts = {}, {}, {}, {}, {}
        TaxClade.markers2lens = self.markers2lens
        TaxClade.markers2exts = self.markers2exts
        TaxClade.taxa2clades = self.taxa2clades

        clades_txt = (l.strip().split("|") for l in mpa_pkl['taxonomy'])        
        for clade in clades_txt:
            father = self.root
            for clade_lev in clade: # !!!!! [:-1]:
                if not clade_lev in father.children:
                    father.add_child( clade_lev )
                    self.all_clades[clade_lev] = father.children[clade_lev]
                if clade_lev[0] == "t":
                    self.taxa2clades[clade_lev[3:]] = father 
                father = father.children[clade_lev]

        
        for k,p in mpa_pkl['markers'].items():
            if k in markers_to_exclude:
                continue
            self.markers2lens[k] = p['len']
            self.markers2clades[k] = p['clade']
            self.add_reads( k, 0  )
            self.markers2exts[k] = p['ext']

    #def set_static( self ):
    #    TaxClade.markers2lens = self.markers2lens
    #    TaxClade.markers2exts = self.markers2exts
    #    TaxClade.taxa2clades = self.taxa2clades

    def set_min_cu_len( self, min_cu_len ):
        TaxClade.min_cu_len = min_cu_len

    def set_stat( self, stat, quantile, avoid_disqm = False ):
        TaxClade.stat = stat
        TaxClade.quantile = quantile
        TaxClade.avoid_disqm = avoid_disqm

    def add_reads(  self, marker, n, 
                    ignore_viruses = False, ignore_eukaryotes = False, 
                    ignore_bacteria = False, ignore_archaea = False  ):
        clade = self.markers2clades[marker]
        cl = self.all_clades[clade]
        if ignore_viruses or ignore_eukaryotes or ignore_bacteria or ignore_archaea:
            cn = cl.get_full_name()
            if ignore_viruses and cn.startswith("k__Viruses"):
                return ""
            if ignore_eukaryotes and cn.startswith("k__Eukaryotes"):
                return ""
            if ignore_archaea and cn.startswith("k__Archaea"):
                return ""
            if ignore_bacteria and cn.startswith("k__Bacteria"):
                return ""
        while len(cl.children) == 1:
            cl = list(cl.children.values())[0]
        cl.markers2nreads[marker] = n
        return cl.get_full_name()
   
    #
    #def set_marker_len( self, marker_len_f ):
    #    self.markers2lens = marker_len_f
    #
    #def set_markers2clade( self, markers2clade_f ):
    #    self.markers2clades = markers2clade_f
    #    for k in self.markers2clades:
    #        self.add_reads( k, 0  )
    #
    #def set_markers2exts( self, markers2exts ):
    #    self.markers2exts = markers2exts

    def clade_profiles( self, tax_lev  ):
        cl2pr = {}
        for k,v in self.all_clades.items():
            if tax_lev and not k.startswith(tax_lev): 
                continue
            prof = v.get_normalized_counts()
            if len(prof) < 1 or not sum([p[1] for p in prof]) > 0.0:
                continue
            cl2pr[v.get_full_name()] = prof
        return cl2pr
            
    def relative_abundances( self, tax_lev  ):
        cl2ab_n = dict([(k,v) for k,v in self.all_clades.items() 
                    if k.startswith("k__") and not v.uncl])
     
        cl2ab, tot_ab = {}, 0.0 
        for k,v in cl2ab_n.items():
            tot_ab += v.compute_abundance()

        for k,v in cl2ab_n.items():
            for cl,ab in v.get_all_abundances():
                if not tax_lev:
                    if cl not in self.all_clades:
                        to = tax_units.index(cl[0])
                        t = tax_units[to-1]
                        cl = t + cl.split("_unclassified")[0][1:]
                        cl = self.all_clades[cl].get_full_name()
                        spl = cl.split("|")
                        cl = "|".join(spl+[tax_units[to]+spl[-1][1:]+"_unclassified"])
                    else:
                        cl = self.all_clades[cl].get_full_name() 
                elif not cl.startswith(tax_lev):
                    continue
                cl2ab[cl] = ab

        ret_d = dict([( k, float(v) / tot_ab if tot_ab else 0.0) for k,v in cl2ab.items()])
        if tax_lev:
            ret_d[tax_lev+"unclassified"] = 1.0 - sum(ret_d.values())
        return ret_d

def map2bbh( blast_outfmt6, input_type = 'bowtie2out'  ):
    if not blast_outfmt6:
        inpf = sys.stdin
    else:
        if blast_outfmt6.endswith(".bz2"):
            inpf = bz2.BZ2File( blast_outfmt6, "r" )
        else:
            inpf = open( blast_outfmt6 )

    reads2markers, reads2maxb = {}, {}
    if input_type == 'bowtie2out':
        for r,c in (l.strip().split('\t') for l in inpf):
            reads2markers[r] = c
    elif input_type == 'sam':
        for o in (l.strip().split('\t') for l in inpf):
            if o[0][0] != '@' and o[2][-1] != '*':
                reads2markers[o[0]] = o[2]
    inpf.close()

    markers2reads = defdict( set )
    for r,m in reads2markers.items():
        markers2reads[m].add( r )

    return markers2reads
    
    
#***************************************************************************
#*                                                                         *
#*  Generate biom output if user required it                               *
#*  Parameters : In pars                                                   *
#*  --biom_output_file : Name of the output biom file generated            *
#*       .....Note :  This is an additional file generated                 *
#*                    in addition to the regular output requested          *
#*  --metadata_delimiter_char: This is the metadata taxonomy               *
#*       separator, defaulting to pipe.                                    *
#*  Example:                                                               *
#*  The pipe | in:                                                         *
#* k__Bacteria|p__Proteobacteria|c__Gammaproteobacteria|o__Vibrionales     *                   
#*                                                                         *
#* Updated by George Weingart george.weingart@gmail.com on 2013/11/23      *
#*                                                                         *
#***************************************************************************
def generate_biom_file(pars):
    SPsInputFile =    pars['output'] 
    cDelim = pars['metadata_delimiter_char']
    if  len(cDelim) != 1:   #If delimter length passed by user not 1 - use default
        cDelim = "|" 
        lSampleIds = [pars['inp'].split('.')[0]]    #The first node of the dataset
    lSampleMetadata = list()    #No metadata for the samples
    dSampleMetadataEntry = dict()    
    dSampleMetadataEntry['metadata']  = None
    lSampleMetadata.append(dSampleMetadataEntry)
    ResultsFile = open(SPsInputFile,'r')
    iLineNum = 0    #Set up counter
    lAbundanceData = list() #Define the Abundance data Table
    lRowEntries = list()    #Row Entries (Samples)
    lObservationMetadata = list()                    
    lObservationIds = list()
    for line1 in ResultsFile:
        iLineNum+=1
        sBugId = line1.split()[0]
        lAbundance = [float(line1.split()[1])]  #The Abundance for this bug
        lAbundanceData.append(lAbundance)   #Add the Abundance of this bug to the table 
        dRowEntry=dict()    #This row entry is a dictionary
        lObservationIds.append(str(iLineNum))   #The record number
        lRowMetaData = sBugId.split(cDelim) #Define list of the Taxonomies for the bug    
        dRowEntry['taxonomy'] = lRowMetaData    #The Metadata
        lObservationMetadata.append(dRowEntry)   #Add row entry to the obs metadata
    ResultsFile.close()
    aAbundanceData = array(lAbundanceData)


    biomResults = table_factory(aAbundanceData,
                  lSampleIds,
                  lObservationIds,
                  lSampleMetadata,
                  lObservationMetadata,
                  constructor=DenseOTUTable)


    jsonBiomResults  = biomResults.getBiomFormatObject('metaphlan_Biom_Output')
    with open(pars['biom_output_file'], 'w') as outfile:
        json.dump(jsonBiomResults, outfile)
    return 0

    

if __name__ == '__main__':
    pars = read_params( sys.argv )

    if pars['inp'] is None and ( pars['input_type'] is None or  pars['input_type'] == 'automatic'): 
        sys.stderr.write( "The --input_type parameter need top be specified when the "
                          "input is provided from the standard input.\n"
                          "Type metaphlan.py -h for more info\n")
        sys.exit(0)

    if pars['input_type'] == 'automatic':
        pars['input_type'] = guess_input_format( pars['inp'] )
        if not pars['input_type']:
            sys.stderr.write( "Sorry, I cannot guess the format of the input file, please "
                              "specify the --input_type parameter \n" )
            sys.exit(1) 

    no_map = False
    if pars['input_type'] == 'multifasta' or pars['input_type'] == 'multifastq':
        bow = pars['bowtie2db'] is not None
        if not bow:
            sys.stderr.write( "No MetaPhlAn BowTie2 database provided\n "
                              "[--bowtie2db options]!\n"
                              "Exiting...\n\n" )
            sys.exit()
        if pars['no_map']:
            pars['bowtie2out'] = tf.NamedTemporaryFile(dir=pars['tmp_dir']).name
            no_map = True
        else:
            if bow and not pars['bowtie2out']:
                if pars['inp'] and "," in  pars['inp']:
                    sys.stderr.write( "Error! --bowtie2out needs to be specified when multiple "
                                      "fastq or fasta files (comma separated) are provided"  )
                    sys.exit()
                pars['bowtie2out'] = ( pars['inp'] if pars['inp'] else "stdin_map") + ".bowtie2out.txt"

            if os.path.exists( pars['bowtie2out'] ):
                sys.stderr.write(   
                    "BowTie2 output file detected: " + pars['bowtie2out'] + "\n"
                    "Please use it as input or remove it if you want to "
                    "re-perform the BowTie2 run.\n"
                    "Exiting...\n\n" )
                sys.exit()

        if bow and not all([os.path.exists(".".join([str(pars['bowtie2db']),p]))
                        for p in ["1.bt2", "2.bt2", "3.bt2","4.bt2","1.bt2","2.bt2"]]):
            sys.stderr.write( "No MetaPhlAn BowTie2 database found "
                              "[--bowtie2db option]! "
                              "(or wrong path provided)."
                              "\nExiting... " )
            sys.exit(1)
       
        if bow:
            run_bowtie2( pars['inp'], pars['bowtie2out'], pars['bowtie2db'], 
                         pars['bt2_ps'], pars['nproc'], file_format = pars['input_type'],
                         exe = pars['bowtie2_exe'] )
            pars['input_type'] = 'bowtie2out'
        
        pars['inp'] = pars['bowtie2out'] # !!!

    with open( pars['mpa_pkl'], 'rb' ) as a:
        mpa_pkl = pickle.loads( bz2.decompress( a.read() ) )

    tree = TaxTree( mpa_pkl )
    #tree.set_marker_len( dict( [(k,p['len']) for k,p in mpa_pkl['markers'].items()] )) 
    #tree.set_markers2clade( dict( [(k,p['clade']) for k,p in mpa_pkl['markers'].items()] )) 
    #tree.set_markers2exts( dict( [(k,p['ext']) for k,p in mpa_pkl['markers'].items()] )) 
    tree.set_min_cu_len( pars['min_cu_len'] )
    #tree.set_static( )
    tree.set_stat( pars['stat'], pars['stat_q'], pars['avoid_disqm']  )

    markers2reads = map2bbh( pars['inp'], pars['input_type'] )
    if no_map:
        os.remove( pars['inp'] )         

    map_out = []
    for marker,reads in markers2reads.items():
        if marker not in tree.markers2lens:
            continue
        tax_seq = tree.add_reads( marker, len(reads), 
                                  ignore_viruses = pars['ignore_viruses'],
                                  ignore_eukaryotes = pars['ignore_eukaryotes'],
                                  ignore_bacteria = pars['ignore_bacteria'],
                                  ignore_archaea = pars['ignore_archaea'],
                                  )
        if tax_seq:
            map_out +=["\t".join([r,tax_seq]) for r in reads]
    
    if pars['output'] is None and pars['output_file'] is not None:
        pars['output'] = pars['output_file']

    with (open(pars['output'],"w") if pars['output'] else sys.stdout) as outf:
        if pars['t'] == 'reads_map':
            outf.write( "\n".join( map_out ) + "\n" )
        elif pars['t'] == 'rel_ab':
            cl2ab = tree.relative_abundances( 
                        pars['tax_lev']+"__" if pars['tax_lev'] != 'a' else None )
            outpred = [(k,round(v*100.0,5)) for k,v in cl2ab.items() if v > 0.0]
            if outpred:
                for k,v in sorted(  outpred, reverse=True,
                                    key=lambda x:x[1]+(100.0*(8-x[0].count("|")))  ): 
                    outf.write( "\t".join( [k,str(v)] ) + "\n" )   
            else:
                outf.write( "unclassified\t100.0\n" )
        elif pars['t'] == 'clade_profiles':
            cl2pr = tree.clade_profiles( pars['tax_lev']+"__" if pars['tax_lev'] != 'a' else None  )
            for c,p in cl2pr.items():
                mn,n = zip(*p)
                outf.write( "\t".join( [""]+[str(s) for s in mn] ) + "\n" )
                outf.write( "\t".join( [c]+[str(s) for s in n] ) + "\n" )
        elif pars['t'] == 'marker_ab_table':
            cl2pr = tree.clade_profiles( pars['tax_lev']+"__" if pars['tax_lev'] != 'a' else None  )
            for v in cl2pr.values():
                outf.write( "\n".join(["\t".join([str(a),str(b/float(pars['nreads'])) if pars['nreads'] else str(b)]) 
                                for a,b in v if b > 0.0]) + "\n" )
        elif pars['t'] == 'marker_pres_table':
            cl2pr = tree.clade_profiles( pars['tax_lev']+"__" if pars['tax_lev'] != 'a' else None  )
            for v in cl2pr.values():
                strout = ["\t".join([str(a),"1"]) for a,b in v if b > pars['pres_th']]
                if strout:
                    outf.write( "\n".join(strout) + "\n" )
                    
    #***************************************************************************
    #* Check if the User requested biom output - if so, generate it            *
    #***************************************************************************
    if pars['biom'] is not None:
        generate_biom_file(pars)
                    

