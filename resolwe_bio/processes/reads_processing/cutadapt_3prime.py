"""Run Cutadapt tool on 3' mRNA-seq datasets."""
import os
import shutil

from plumbum import TEE

from resolwe.process import (
    Process,
    Cmd,
    SchedulingClass,
    DataField,
    ListField,
    GroupField,
    FileField,
    FileHtmlField,
    IntegerField
)


class Cutadapt3Prime(Process):
    """Process 3' mRNA-seq datasets using Cutadapt tool."""

    slug = 'cutadapt-3prime-single'
    name = "Cutadapt (3' mRNA-seq, single-end)"
    process_type = 'data:reads:fastq:single:cutadapt:'
    version = '1.0.1'
    category = 'Other'
    shaduling_class = SchedulingClass.BATCH
    entity = {'type': 'sample'}
    requirements = {
        'expression-engine': 'jinja',
        'executor': {
            'docker': {
                'image': 'resolwebio/rnaseq:4.7.0'
            },
        },
        'resources': {
            'cores': 10,
            'memory': 16384,
        },
    }
    data_name = '{{ reads|sample_name|default("?") }}'

    class Input:
        """Input fields."""

        reads = DataField('reads:fastq:single', label='Select sample(s)')

        class Options:
            """Options."""

            nextseq_trim = IntegerField(
                label="NextSeq/NovaSeq trim",
                description="NextSeq/NovaSeq-specific quality trimming. Trims also dark "
                            "cycles appearing as high-quality G bases. This option is mutually "
                            "exclusive with the use of standard quality-cutoff trimming and is "
                            "suitable for the use with data generated by the recent Illumina "
                            "machines that utilize two-color chemistry to encode the four bases.",
                default=10,
            )

            quality_cutoff = IntegerField(
                label="Quality cutoff",
                description="Trim low-quality bases from 3' end of each read before adapter "
                            "removal. The use of this option will override the use of "
                            "NextSeq/NovaSeq trim option.",
                required=False,
            )

            min_len = IntegerField(
                label="Discard reads shorter than specified minimum length.",
                default=20,
            )

            min_overlap = IntegerField(
                label="Mimimum overlap",
                description="Minimum overlap between adapter and read for an adapter to be found.",
                default=20,
            )

            times = IntegerField(
                label="Remove up to a specified number of adapters from each read.",
                default=2,
            )

        options = GroupField(Options, label="Options")

    class Output:
        """Output fields."""

        fastq = ListField(FileField(), label='Reads file.')
        report = FileField(label='Cutadapt report')
        fastqc_url = ListField(FileHtmlField(), label='Quality control with FastQC.')
        fastqc_archive = ListField(FileField(), label='Download FastQC archive.')

    def run(self, inputs, outputs):
        """Run analysis."""
        # Get input reads file name (for the first of the possible multiple lanes)
        name = os.path.basename(inputs.reads.fastq[0].path).strip('.fastq.gz')
        # Concatenate multi-lane read files
        (Cmd['cat'][[reads.path for reads in inputs.reads.fastq]] > 'input_reads.fastq.gz')()

        if inputs.options.quality_cutoff is not None:
            read_trim_cutoff = '--quality-cutoff={}'.format(inputs.options.quality_cutoff)
        else:
            read_trim_cutoff = '--nextseq-trim={}'.format(inputs.options.nextseq_trim)

        first_pass_input = [
            '-m', inputs.options.min_len,
            '-O', inputs.options.min_overlap,
            '-n', inputs.options.times,
            '-a', 'polyA=A{20}',
            '-a', 'QUALITY=G{20}',
            '-j', self.requirements.resources.cores,
            'input_reads.fastq.gz',
        ]

        second_pass_input = [
            '-m', inputs.options.min_len,
            read_trim_cutoff,
            '-a', 'truseq=A{18}AGATCGGAAGAGCACACGTCTGAACTCCAGTCAC',
            '-j', self.requirements.resources.cores,
            '-',
        ]

        third_pass_input = [
            '-m', inputs.options.min_len,
            '-O', inputs.options.min_overlap,
            '-g', 'truseq=A{18}AGATCGGAAGAGCACACGTCTGAACTCCAGTCAC',
            '--discard-trimmed',
            '-j', self.requirements.resources.cores,
            '-o', '{}_trimmed.fastq.gz'.format(name),
            '-',
        ]

        # Run Cutadapt, write analysis reports into a report file
        (
            Cmd['cutadapt'][first_pass_input]
            | Cmd['cutadapt'][second_pass_input]
            | Cmd['cutadapt'][third_pass_input] > 'cutadapt_report.txt'
        )()

        # Prepare final FASTQC report
        fastqc_args = ['{}_trimmed.fastq.gz'.format(name), 'fastqc', 'fastqc_archive', 'fastqc_url', '--nogroup']
        return_code, _, _ = Cmd['fastqc.sh'][fastqc_args] & TEE(retcode=None)
        if return_code:
            self.error("Error while preparing FASTQC report.")

        # Save the outputs
        outputs.fastq = ['{}_trimmed.fastq.gz'.format(name)]
        outputs.report = 'cutadapt_report.txt'